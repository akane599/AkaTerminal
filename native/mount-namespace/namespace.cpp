// Root-only mount namespace owner for chroots. No global mount mutation.
// Validated recovery preserves a surviving namespace or requires an exclusive empty lease.
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <fcntl.h>
#include <poll.h>
#include <sched.h>
#include <stdexcept>
#include <string>
#include <sstream>
#include <vector>
#include <sys/file.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

namespace {
struct Fd {
    int n = -1;
    explicit Fd(int value = -1) : n(value) {}
    ~Fd() { if (n >= 0) close(n); }
    Fd(const Fd&) = delete;
    Fd& operator=(const Fd&) = delete;
};
[[noreturn]] void fail(const std::string& message) { throw std::runtime_error(message); }
void need(bool condition, const std::string& message) { if (!condition) fail(message); }
void sysok(int value, const char* operation) {
    if (value < 0) fail(std::string(operation) + ": " + strerror(errno));
}
std::string read_fd(int fd) {
    need(fd >= 0, "cannot open input");
    std::string out;
    char buf[4096];
    for (;;) {
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n < 0 && errno == EINTR) continue;
        sysok(static_cast<int>(n), "read");
        if (!n) return out;
        out.append(buf, static_cast<size_t>(n));
        need(out.size() < 8 * 1024 * 1024, "input too large");
    }
}
std::string read_path(const std::string& path) {
    Fd fd(open(path.c_str(), O_RDONLY | O_CLOEXEC));
    return read_fd(fd.n);
}
struct Identity {
    unsigned long long dev = 0, ino = 0;
    bool operator==(const Identity& other) const { return dev == other.dev && ino == other.ino; }
    bool operator!=(const Identity& other) const { return !(*this == other); }
};
Identity identity(int fd) {
    struct stat st{};
    sysok(fstat(fd, &st), "fstat");
    return {static_cast<unsigned long long>(st.st_dev), static_cast<unsigned long long>(st.st_ino)};
}
Identity self_ns() { Fd fd(open("/proc/self/ns/mnt", O_RDONLY | O_CLOEXEC)); return identity(fd.n); }
std::string boot() {
    auto s = read_path("/proc/sys/kernel/random/boot_id");
    need(s.size() == 37 && s.back() == '\n', "invalid boot identity");
    s.pop_back(); return s;
}
unsigned long long start(int proc_fd) {
    Fd fd(openat(proc_fd, "stat", O_RDONLY | O_CLOEXEC));
    auto s = read_fd(fd.n);
    auto end = s.rfind(')');
    need(end != std::string::npos, "invalid process identity");
    std::istringstream fields(s.substr(end + 2));
    std::string field;
    for (int i = 3; i <= 22; ++i) need(bool(fields >> field), "short process identity");
    size_t used = 0;
    auto value = std::stoull(field, &used);
    need(used == field.size() && value, "invalid process start");
    return value;
}
std::string unescape(const std::string& s) {
    std::string out;
    for (size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '\\') {
            need(i + 3 < s.size(), "invalid mount escape");
            unsigned x = 0;
            for (unsigned j = 1; j <= 3; ++j) {
                need(s[i+j] >= '0' && s[i+j] <= '7', "invalid mount escape");
                x = x * 8 + static_cast<unsigned>(s[i+j] - '0');
            }
            out += static_cast<char>(x); i += 3;
        } else out += s[i];
    }
    return out;
}
bool under(const std::string& path, const std::string& root) {
    return path == root || path.compare(0, root.size() + 1, root + "/") == 0;
}
void no_global_guest_mounts(const std::string& root) {
    std::istringstream lines(read_path("/proc/1/mountinfo"));
    std::string line; unsigned count = 0;
    while (std::getline(lines, line)) {
        std::istringstream f(line); std::string x;
        for (int i=0; i<5; ++i) need(bool(f >> x), "invalid global mountinfo");
        need(!under(unescape(x), root), "guest already mounted globally; cold transition required");
        ++count;
    }
    need(count > 0, "empty global mountinfo");
}
void require_private() {
    std::istringstream lines(read_path("/proc/self/mountinfo"));
    std::string line; unsigned count = 0;
    while (std::getline(lines,line)) {
        std::istringstream f(line); std::string x;
        for(int i=0;i<6;++i) need(bool(f >> x), "invalid mountinfo");
        while (f >> x && x != "-")
            need(x.rfind("shared:",0) && x.rfind("master:",0) && x.rfind("propagate_from:",0),
                 "namespace is not recursively private");
        need(x == "-", "invalid mountinfo separator"); ++count;
    }
    need(count > 0, "empty mount view");
}
void root_file(int fd, bool directory) {
    struct stat st{}; sysok(fstat(fd, &st), "fstat protected file");
    need(st.st_uid == 0 && !(st.st_mode & 0077) &&
         (directory ? S_ISDIR(st.st_mode) : S_ISREG(st.st_mode) && st.st_nlink == 1),
         "state must be root-owned, private, regular and unlinked elsewhere");
}
int state_dir(const std::string& path) {
    const std::string base = "/data/adb/fluxlinux";
    need(path.rfind(base + "/",0) == 0 && path.size() < 220, "invalid state path");
    Fd adb(open("/data/adb",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC));
    sysok(adb.n,"open /data/adb"); root_file(adb.n,true);
    int at = dup(adb.n); sysok(at,"dup");
    std::istringstream parts(path.substr(std::string("/data/adb/").size()));
    std::string part;
    try {
        while (std::getline(parts,part,'/')) {
            need(!part.empty() && part != "." && part != "..", "invalid state component");
            if (mkdirat(at,part.c_str(),0700)) need(errno == EEXIST,"mkdir state failed");
            int next=openat(at,part.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
            sysok(next,"open state component"); close(at); at=next; root_file(at,true);
        }
    } catch (...) { close(at); throw; }
    return at;
}
struct Record {
    std::string boot_id;
    int pid=0;
    unsigned long long ticks=0;
    Identity ns, root;
};
Record record(int dir) {
    Fd fd(openat(dir,"owner",O_RDONLY|O_NOFOLLOW|O_CLOEXEC));
    sysok(fd.n,"open owner (create first)"); root_file(fd.n,false);
    std::istringstream s(read_fd(fd.n)); Record r; std::string version,extra;
    need(bool(s >> version >> r.boot_id >> r.pid >> r.ticks >> r.ns.dev >> r.ns.ino >> r.root.dev >> r.root.ino)
         && version == "flux-mntns-1" && !(s >> extra) && r.pid>1 && r.ticks && r.ns.ino,
         "invalid owner record");
    need(r.boot_id == boot(), "owner belongs to another boot; explicit retirement required");
    return r;
}
void write_all(int fd,const std::string& s) {
    size_t done=0;
    while(done<s.size()) {
        ssize_t n=write(fd,s.data()+done,s.size()-done);
        if(n<0 && errno==EINTR) continue;
        need(n>0,"write failed"); done+=static_cast<size_t>(n);
    }
}
int pin_owner(const Record& r, Identity root) {
    need(r.root == root,"rootfs identity changed");
    Fd proc(open(("/proc/"+std::to_string(r.pid)).c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC));
    sysok(proc.n,"owner disappeared; no automatic replacement");
    struct stat st{}; sysok(fstat(proc.n,&st),"owner stat");
    need(st.st_uid==0 && start(proc.n)==r.ticks,"owner identity mismatch");
    int fd=openat(proc.n,"ns/mnt",O_RDONLY|O_CLOEXEC); sysok(fd,"pin owner namespace");
    try {
        need(identity(fd)==r.ns && start(proc.n)==r.ticks,"owner namespace changed");
        Fd init(open("/proc/1/ns/mnt",O_RDONLY|O_CLOEXEC));
        need(identity(fd)!=identity(init.n),"refuse global namespace");
    } catch (...) { close(fd); throw; }
    return fd;
}
void no_other_users(const Record& r) {
    DIR* d=opendir("/proc"); need(d,"open proc");
    try {
        while(auto* e=readdir(d)) {
            char* end=nullptr; long pid=strtol(e->d_name,&end,10);
            if(!*e->d_name || *end || pid<=0 || pid==r.pid || pid==getpid()) continue;
            Fd fd(open((std::string("/proc/")+e->d_name+"/ns/mnt").c_str(),O_RDONLY|O_CLOEXEC));
            if(fd.n<0) { need(errno==ENOENT || errno==ESRCH,"cannot inspect namespace user"); continue; }
            need(identity(fd.n)!=r.ns,"namespace still has live processes");
        }
    } catch (...) { closedir(d); throw; }
    closedir(d);
}
void close_except(int keep, int keep_ns = -1) {
    DIR* d=opendir("/proc/self/fd"); need(d,"open fd list");
    int listfd=dirfd(d);
    while(auto* e=readdir(d)) {
        char* end=nullptr; long fd=strtol(e->d_name,&end,10);
        if(*e->d_name && !*end && fd>2 && fd!=keep && fd!=keep_ns && fd!=listfd) close(static_cast<int>(fd));
    }
    closedir(d);
}
void recovery_fault(const char* point) {
#ifdef FLUX_RECOVERY_TEST
    const char* requested=getenv("FLUX_RECOVERY_FAULT");
    if(requested && !strcmp(requested,point)) _exit(86);
#else
    (void)point;
#endif
}
void spawn_owner(const std::string& state,const std::string& root,Identity root_id,
                 int dir,int reuse_ns=-1) {
    int pipes[2]; sysok(pipe2(pipes,O_CLOEXEC),"pipe"); Fd input(pipes[0]),output(pipes[1]);
    pid_t first=fork(); sysok(first,"fork owner");
    if(first==0) {
        try {
            sysok(setsid(),"setsid"); pid_t second=fork(); sysok(second,"fork detached owner");
            if(second) _exit(0);
            close_except(output.n,reuse_ns);
            Fd null(open("/dev/null",O_RDWR|O_CLOEXEC)); sysok(null.n,"open null");
            for(int n=0;n<3;++n) sysok(dup2(null.n,n),"redirect owner");
            sysok(chdir("/"),"owner cwd");
            if(reuse_ns>=0) {
                sysok(setns(reuse_ns,CLONE_NEWNS),"rejoin surviving namespace");
                need(self_ns()==identity(reuse_ns),"surviving namespace changed");
                require_private();
                std::istringstream mounts(read_path("/proc/self/mountinfo"));
                std::string line;unsigned anchors=0;
                while(std::getline(mounts,line)) {
                    std::istringstream fields(line);std::string field;
                    for(int i=0;i<5;++i)need(bool(fields>>field),"invalid surviving mountinfo");
                    if(unescape(field)==root)++anchors;
                }
                need(anchors==1,"surviving root mount anchor missing or ambiguous");
            } else {
                Fd init(open("/proc/1/ns/mnt",O_RDONLY|O_CLOEXEC));
                sysok(setns(init.n,CLONE_NEWNS),"join init before copy");
                sysok(chdir("/"),"owner cwd");
                no_global_guest_mounts(root);
                sysok(unshare(CLONE_NEWNS),"unshare");
                need(self_ns()!=identity(init.n),"namespace did not change");
                sysok(mount(nullptr,"/",nullptr,MS_PRIVATE|MS_REC,nullptr),"make private"); require_private();
                // dev/suid belongs to this guest's mount, never Android's /data
                // superblock or global mount. No inherited mounts exist below root.
                sysok(mount(root.c_str(),root.c_str(),nullptr,MS_BIND,nullptr),"bind private rootfs");
                sysok(mount(nullptr,root.c_str(),nullptr,MS_REMOUNT|MS_BIND|MS_RELATIME,nullptr),
                      "set private rootfs mount flags");
            }
            Fd statefd(open(state.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC)); root_file(statefd.n,true);
            Fd rootfd(open(root.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC));
            need(identity(rootfd.n)==root_id,"rootfs changed during create");
            Fd proc(open("/proc/self",O_RDONLY|O_DIRECTORY|O_CLOEXEC));
            auto ns=self_ns();
            std::ostringstream row;
            row << "flux-mntns-1 " << boot() << ' ' << getpid() << ' ' << start(proc.n)
                << ' ' << ns.dev << ' ' << ns.ino << ' ' << root_id.dev << ' ' << root_id.ino << '\n';
            Fd out(openat(statefd.n,"owner.new",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600));
            sysok(out.n,"create owner record"); write_all(out.n,row.str()); sysok(fsync(out.n),"fsync owner");
            recovery_fault("before-publish");
            sysok(renameat(statefd.n,"owner.new",statefd.n,"owner"),"publish owner");
            sysok(fsync(statefd.n),"fsync owner directory");
            recovery_fault("after-publish");
            write_all(output.n,"ready\n"); close(output.n); output.n=-1;
            for(;;) pause();
        } catch(const std::exception& e) {
            // A dead creator leaves 'creating' as evidence; never remove another owner.
            try { write_all(output.n,std::string("error: ")+e.what()+"\n"); } catch(...) {}
            _exit(1);
        }
    }
    close(output.n); output.n=-1;
    int status=0; while(waitpid(first,&status,0)<0) need(errno==EINTR,"wait owner fork");
    need(WIFEXITED(status)&&WEXITSTATUS(status)==0,"owner fork failed");
    pollfd p{input.n,POLLIN,0}; int ready;
    do { ready=poll(&p,1,15000); } while(ready<0 && errno==EINTR);
    need(ready>0,"owner readiness timed out; creation remains latched");
    need(read_fd(input.n)=="ready\n","owner failed; creation remains latched");
    auto r=record(dir); Fd ns(pin_owner(r,root_id));
}
void create(const std::string& state,const std::string& root, Identity root_id,int dir) {
    struct stat old{};
    if(!fstatat(dir,"owner",&old,AT_SYMLINK_NOFOLLOW)) {
        auto r=record(dir); Fd ns(pin_owner(r,root_id)); return;
    }
    need(errno==ENOENT,"cannot inspect owner");
    no_global_guest_mounts(root);
    // A failed/abrupt creation remains latched. Never start a second owner blindly.
    Fd intent(openat(dir,"creating",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600));
    sysok(intent.n,"creation already attempted; inspect state");
    write_all(intent.n,boot()+"\n"); sysok(fsync(intent.n),"fsync intent"); sysok(fsync(dir),"fsync state");
    spawn_owner(state,root,root_id,dir);
}
// A mismatching/reused PID is ambiguous and remains refused. Only confirmed
// absence of the recorded process enters recovery; no signal is sent here.
bool owner_missing(const Record& r,Identity root_id) {
    need(r.root==root_id,"rootfs identity changed");
    Fd proc(open(("/proc/"+std::to_string(r.pid)).c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC));
    if(proc.n<0) {
        need(errno==ENOENT || errno==ESRCH,"cannot inspect missing owner");
        return true;
    }
    struct stat st{};sysok(fstat(proc.n,&st),"owner stat");
    need(st.st_uid==0 && start(proc.n)==r.ticks,"owner identity mismatch");
    return false;
}
// Namespace inode numbers can be recycled immediately after the last reference
// dies. A matching number alone cannot authorize adoption of another namespace.
bool current_namespace_has_guest(const std::string& root,Identity root_id) {
    std::istringstream mounts(read_path("/proc/self/mountinfo"));
    std::string line;unsigned anchors=0;
    while(std::getline(mounts,line)) {
        std::istringstream fields(line);std::string field;
        for(int i=0;i<5;++i)need(bool(fields>>field),"invalid candidate mountinfo");
        if(unescape(field)==root)++anchors;
    }
    if(!anchors)return false;
    need(anchors==1,"ambiguous surviving guest root");
    require_private();
    Fd rootfd(open(root.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC));
    need(identity(rootfd.n)==root_id,"surviving guest root identity changed");
    return true;
}
bool namespace_has_guest(int ns,const std::string& root,Identity root_id) {
    pid_t child=fork();sysok(child,"fork namespace identity probe");
    if(child==0) {
        try {
            sysok(setns(ns,CLONE_NEWNS),"probe surviving namespace");
            sysok(chdir("/"),"probe cwd");
            _exit(current_namespace_has_guest(root,root_id)?0:3);
        } catch(...) {_exit(125);}
    }
    int status=0;while(waitpid(child,&status,0)<0)need(errno==EINTR,"wait namespace identity probe");
    need(WIFEXITED(status) && (WEXITSTATUS(status)==0 || WEXITSTATUS(status)==3),
         "cannot validate surviving guest namespace");
    return WEXITSTATUS(status)==0;
}
int surviving_namespace(const Record& r,const std::string& root,Identity root_id) {
    DIR* d=opendir("/proc");need(d,"open proc for recovery");
    int selected=-1;
    try {
        errno=0;
        while(auto* e=readdir(d)) {
            char* end=nullptr;long pid=strtol(e->d_name,&end,10);
            if(!*e->d_name || *end || pid<=0) { errno=0; continue; }
            Fd ns(open((std::string("/proc/")+e->d_name+"/ns/mnt").c_str(),O_RDONLY|O_CLOEXEC));
            if(ns.n<0) { need(errno==ENOENT || errno==ESRCH,"cannot inspect surviving namespace");errno=0;continue; }
            if(identity(ns.n)==r.ns && namespace_has_guest(ns.n,root,root_id)) { selected=dup(ns.n);sysok(selected,"pin surviving namespace");break; }
            errno=0;
        }
        need(selected>=0 || errno==0,"cannot enumerate surviving namespaces");
    } catch(...) { if(selected>=0)close(selected);closedir(d);throw; }
    closedir(d);return selected;
}
void ensure_owner(const std::string& state,const std::string& root,Identity root_id,
                  int dir,int gate) {
    // Separate publication mutex permits repair while live guest clients hold
    // shared leases. A destructive fresh namespace still requires an EX lease.
    Fd repair(openat(dir,"recovery.lock",O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC,0600));
    root_file(repair.n,false);sysok(flock(repair.n,LOCK_EX|LOCK_NB),"owner recovery busy");
    sysok(flock(gate,LOCK_SH|LOCK_NB),"namespace busy");
    struct stat st{};
    if(fstatat(dir,"owner",&st,AT_SYMLINK_NOFOLLOW)) {
        need(errno==ENOENT,"cannot inspect owner");
        sysok(flock(gate,LOCK_EX|LOCK_NB),"namespace busy");
        create(state,root,root_id,dir);return;
    }
    auto r=record(dir);
    if(!owner_missing(r,root_id)) { Fd ns(pin_owner(r,root_id));return; }
    Fd ns(surviving_namespace(r,root,root_id));
    if(ns.n<0) {
        sysok(flock(gate,LOCK_EX|LOCK_NB),"old namespace still has client leases");
        Fd again(surviving_namespace(r,root,root_id));
        need(again.n<0,"guest namespace appeared during exclusive admission");
        no_global_guest_mounts(root);
        need(owner_missing(r,root_id),"owner reappeared");
    }
    std::string key=std::to_string(r.pid)+"-"+std::to_string(r.ticks)+"-"+std::to_string(r.ns.ino);
    // Durable intent prevents a second spawn after an ambiguous interrupted
    // recovery. Original creating/retired records are never removed or replayed.
    Fd intent(openat(dir,("recover-"+key+".intent").c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600));
    sysok(intent.n,"recovery already attempted; inspect state");
    Fd prior(openat(dir,"owner",O_RDONLY|O_NOFOLLOW|O_CLOEXEC));root_file(prior.n,false);
    std::string original=read_fd(prior.n);
    write_all(intent.n,std::string(ns.n>=0?"reuse\n":"fresh\n")+original);
    sysok(fsync(intent.n),"fsync recovery intent");sysok(fsync(dir),"fsync recovery directory");
    recovery_fault("after-intent");
    Fd history(openat(dir,("owner-"+key+".history").c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600));
    sysok(history.n,"owner history already exists");write_all(history.n,original);
    sysok(fsync(history.n),"fsync owner history");sysok(fsync(dir),"fsync owner history directory");
    recovery_fault("after-history");
    spawn_owner(state,root,root_id,dir,ns.n);
}
volatile sig_atomic_t running_child_fd=-1;
void forward(int sig) {
    if(running_child_fd>=0) syscall(SYS_pidfd_send_signal,running_child_fd,sig,nullptr,0);
}
constexpr int signals[]={SIGHUP,SIGINT,SIGQUIT,SIGTERM,SIGWINCH};
int execute(int ns,char** command) {
    if(self_ns()==identity(ns)) { require_private(); execvp(command[0],command); sysok(-1,"exec nested"); }
    sigset_t blocked, previous;
    sigemptyset(&blocked);
    for(int sig:signals) sigaddset(&blocked,sig);
    sysok(sigprocmask(SIG_BLOCK,&blocked,&previous),"block forwarding signals");
    for(int sig:signals) signal(sig,forward);
    pid_t child=fork(); sysok(child,"fork client");
    if(child==0) {
        for(int sig:signals) signal(sig,SIG_DFL);
        sysok(sigprocmask(SIG_SETMASK,&previous,nullptr),"restore child signals");
        try {
            sysok(setns(ns,CLONE_NEWNS),"enter owner namespace");
            sysok(chdir("/"),"client cwd"); require_private();
            execvp(command[0],command); sysok(-1,"exec client");
        } catch(const std::exception& e) { dprintf(2,"flux-mntns: %s\n",e.what()); _exit(125); }
    }
    Fd childfd(static_cast<int>(syscall(SYS_pidfd_open,child,0)));
    if(childfd.n<0) {
        // Still our unreaped child, so its PID cannot have been reused here.
        kill(child,SIGTERM);
        int ignored=0; while(waitpid(child,&ignored,0)<0 && errno==EINTR) {}
        fail("cannot pin client process");
    }
    running_child_fd=childfd.n;
    sysok(sigprocmask(SIG_SETMASK,&previous,nullptr),"restore monitor signals");
    int status=0; while(waitpid(child,&status,0)<0) need(errno==EINTR,"wait client");
    running_child_fd=-1;
    return WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
}
} // namespace

int main(int argc,char** argv) {
    try {
        need(getuid()==0 && geteuid()==0,"root required");
        need(argc>=4,"usage: flux-mntns create|ensure|run|exclusive|remove|inside|inspect|retire|preflight STATE ROOTFS [-- CMD...]");
        std::string mode=argv[1],state=argv[2],root=argv[3];
        bool run=mode=="run" || mode=="exclusive" || mode=="remove";
        need((run && argc>=6 && std::string(argv[4])=="--") || (!run && argc==4),"invalid arguments");
        need(run || mode=="create" || mode=="ensure" || mode=="inside" || mode=="inspect" || mode=="retire" || mode=="preflight","unknown operation");
        need(root.rfind("/data/local/tmp/",0)==0 && root.find_first_of(" \t\r\n\\")==std::string::npos,
             "invalid rootfs path");
        char* canonical=realpath(root.c_str(),nullptr); need(canonical,"rootfs missing");
        std::string resolved(canonical); free(canonical); need(resolved==root,"rootfs must be canonical");
        Fd rootfd(open(root.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC));
        struct stat rootstat{}; sysok(fstat(rootfd.n,&rootstat),"rootfs stat");
        need(rootstat.st_uid==0 && !(rootstat.st_mode&0022),"rootfs must be root-owned and not writable by others");
        auto root_id=identity(rootfd.n);
        // Read-only admission probe: never create state, fork, unshare or mount.
        if(mode=="preflight") { no_global_guest_mounts(root); return 0; }
        Fd dir(state_dir(state));
        Fd gate(openat(dir.n,"gate.lock",O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC,0600)); root_file(gate.n,false);
        if(mode=="ensure") { ensure_owner(state,root,root_id,dir.n,gate.n);return 0; }
        if(mode=="inside") {
            struct stat owner{};
            if(fstatat(dir.n,"owner",&owner,AT_SYMLINK_NOFOLLOW)) {
                need(errno==ENOENT,"cannot inspect owner");
                return 3; // ordinary outside/no-owner result; corruption is 125.
            }
            auto r=record(dir.n);need(r.root==root_id,"rootfs identity changed");
            if(self_ns()==r.ns && current_namespace_has_guest(root,root_id))return 0;
            if(owner_missing(r,root_id))return 4; // ensure must validate recovery
            Fd ns(pin_owner(r,root_id));return 3;
        }
        // Every run holds a shared lease in its monitor, independent of guest FD closing.
        // Nested calls already in the pinned namespace reuse the outer monitor's lease.
        if(run) {
            auto r=record(dir.n);need(r.root==root_id,"rootfs identity changed");
            if(self_ns()==r.ns && current_namespace_has_guest(root,root_id)) {
                need(mode=="run","cannot upgrade a nested session to exclusive");
                Fd ns(open("/proc/self/ns/mnt",O_RDONLY|O_CLOEXEC));
                return execute(ns.n,argv+5);
            }
        }
        struct stat existing{};
        bool existing_create=mode=="create" && !fstatat(dir.n,"owner",&existing,AT_SYMLINK_NOFOLLOW);
        sysok(flock(gate.n,((mode=="run" || mode=="inspect" || existing_create)?LOCK_SH:LOCK_EX)|LOCK_NB),"namespace busy");
        if(existing_create) { auto r=record(dir.n); Fd ns(pin_owner(r,root_id)); return 0; }
        if(mode=="create") { create(state,root,root_id,dir.n); return 0; }
        auto r=record(dir.n); Fd ns(pin_owner(r,root_id));
        if(mode=="inspect") {
            printf("{\"pid\":%d,\"start\":%llu,\"namespace\":%llu,\"root_inode\":%llu}\n",
                   r.pid,r.ticks,r.ns.ino,r.root.ino); return 0;
        }
        if(mode=="exclusive" || mode=="remove" || mode=="retire") no_other_users(r);
        if(mode=="remove") {
            int rc=execute(ns.n,argv+5);
            if(rc) return rc; // failed uninstall keeps its owner for diagnosis/retry.
        }
        if(mode=="retire" || mode=="remove") {
            Fd pidfd(static_cast<int>(syscall(SYS_pidfd_open,r.pid,0))); sysok(pidfd.n,"pin owner process");
            Fd again(pin_owner(r,root_id));
            need(identity(again.n)==identity(ns.n),"owner changed before retire");
            sysok(static_cast<int>(syscall(SYS_pidfd_send_signal,pidfd.n,SIGTERM,nullptr,0)),"retire owner");
            pollfd p{pidfd.n,POLLIN,0}; int rc;
            do { rc=poll(&p,1,5000); } while(rc<0 && errno==EINTR);
            need(rc>0,"owner did not exit");
            no_other_users(r);
            // Keep the record as a tombstone; this experimental helper never resets state.
            sysok(renameat(dir.n,"owner",dir.n,"retired"),"record retirement");
            sysok(fsync(dir.n),"fsync retirement"); return 0;
        }
        return execute(ns.n,argv+5);
    } catch(const std::exception& e) {
        fprintf(stderr,"flux-mntns: %s\n",e.what()); return 125;
    }
}
