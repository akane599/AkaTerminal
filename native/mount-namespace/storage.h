// Included inside namespace.cpp's anonymous namespace.
struct StorageMount { unsigned long long id=0; std::string point,type; };
std::vector<StorageMount> storage_mounts(const std::string& file) {
    std::istringstream lines(read_path(file)); std::string line;
    std::vector<StorageMount> result;
    while(std::getline(lines,line)) {
        std::istringstream fields(line);StorageMount m;std::string x;
        need(bool(fields>>m.id),"invalid storage mount ID");
        for(int i=0;i<4;++i)need(bool(fields>>x),"short storage mount record");
        m.point=unescape(x);
        while(fields>>x && x!="-"){}
        need(x=="-" && bool(fields>>m.type),"invalid storage filesystem");
        result.push_back(m);
    }
    need(!result.empty(),"empty storage mount view");return result;
}
unsigned long long storage_mount_id(int fd) {
    std::istringstream lines(read_path("/proc/self/fdinfo/"+std::to_string(fd)));
    std::string line;
    while(std::getline(lines,line))if(line.rfind("mnt_id:",0)==0) {
        std::istringstream value(line.substr(7));unsigned long long id=0;
        need(bool(value>>id) && id,"invalid pinned storage mount ID");return id;
    }
    fail("missing pinned storage mount ID");
}
void repair_storage(int dir,const std::string& root) {
    require_private();
    Fd lock(openat(dir,"storage.lock",O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC,0600));root_file(lock.n,false);
    sysok(flock(lock.n,LOCK_EX|LOCK_NB),"storage recovery busy");
    const std::string target=root+"/sdcard";
    auto mounts=storage_mounts("/proc/self/mountinfo");StorageMount old;unsigned count=0;
    for(const auto& m:mounts)if(under(m.point,target)) {
        need(m.point==target,"storage has nested mounts");old=m;++count;
    }
    need(count<=1,"storage has stacked mounts");
    const bool disconnected=count==1;
    struct stat st{};
    if(disconnected) {
        need(old.type=="fuse","storage is not FUSE");
        if(!stat(target.c_str(),&st)) { need(S_ISDIR(st.st_mode),"storage is not a directory");return; }
        need(errno==ENOTCONN,"storage error is not a disconnected FUSE server");
    }
    // O_PATH pins a disconnected mount without asking its dead FUSE server.
    // fstat on this FD would itself return ENOTCONN; verify the mount ID instead.
    Fd previous(disconnected ? open(target.c_str(),O_PATH|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC) : -1);
    if(disconnected) {
        sysok(previous.n,"pin disconnected storage");
        need(storage_mount_id(previous.n)==old.id,"storage target changed");
    }
    bool test_source=false;
    std::string source="/proc/1/root/storage/emulated/0";
#ifdef FLUX_RECOVERY_TEST
    if(const char* test=getenv("FLUX_STORAGE_SOURCE")) { source=test;test_source=true; }
#endif
    Fd fresh(open(source.c_str(),O_PATH|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC));
    sysok(fresh.n,"pin current Android storage");
    auto fresh_id=identity(fresh.n); // Requires a live FUSE server before mutation.
    struct statfs fs{};sysok(fstatfs(fresh.n,&fs),"inspect current storage filesystem");
    need(fs.f_type==0x65735546,"current Android storage is not FUSE");
#ifndef FLUX_RECOVERY_TEST
    bool found=false;
    for(const auto& m:storage_mounts("/proc/1/mountinfo"))
        if(m.id==storage_mount_id(fresh.n) && m.type=="fuse")found=true;
    need(found,"current storage is not an init mount");
#endif
    need(storage_mount_id(fresh.n)!=old.id,"replacement is the disconnected mount");
    // Last check before detaching; never act on a different/stacked target.
    auto latest=storage_mounts("/proc/self/mountinfo");count=0;
    for(const auto& m:latest)if(under(m.point,target)) {
        need(m.point==target && m.id==old.id,"storage changed before repair");++count;
    }
    need(count==(disconnected?1u:0u),"storage changed before repair");
    // A plain bind cannot reattach an already detached mount on this kernel.
    // Clone the old tree before detach, so rollback has a move_mount handle.
    constexpr unsigned tree_clone=1, move_from_empty=4, move_to_empty=0x40;
    // Linux rejects cloning a mount belonging to a different namespace.
    // Visit init only to obtain a detached clone, then return before attachment.
    Fd guest_ns(open("/proc/self/ns/mnt",O_RDONLY|O_CLOEXEC));sysok(guest_ns.n,"pin guest namespace");
    if(!test_source) {
        Fd init_ns(open("/proc/1/ns/mnt",O_RDONLY|O_CLOEXEC));sysok(init_ns.n,"pin init namespace");
        sysok(setns(init_ns.n,CLONE_NEWNS),"enter storage source namespace");
    }
    int cloned=static_cast<int>(syscall(SYS_open_tree,fresh.n,"",tree_clone|O_CLOEXEC|AT_EMPTY_PATH));
    int clone_errno=errno;
    Fd replacement(cloned);
    if(!test_source)sysok(setns(guest_ns.n,CLONE_NEWNS),"return to guest namespace");
    require_private();errno=clone_errno;
    sysok(replacement.n,"clone current storage across namespaces");
    // A clone inherits init storage propagation. Make the detached clone private
    // before attaching it; never change propagation on the init mount itself.
    struct { uint64_t set,clear,propagation,userns; } attrs{0,0,MS_PRIVATE,0};
    sysok(static_cast<int>(syscall(SYS_mount_setattr,replacement.n,"",AT_EMPTY_PATH,
        &attrs,sizeof(attrs))),"make storage clone private");
    Fd rollback(disconnected ? static_cast<int>(syscall(SYS_open_tree,previous.n,"",
        tree_clone|O_CLOEXEC|AT_EMPTY_PATH)) : -1);
    if(disconnected) {
        sysok(rollback.n,"clone disconnected storage for rollback");
        sysok(umount2(target.c_str(),MNT_DETACH|UMOUNT_NOFOLLOW),"detach disconnected guest storage");
    }
    bool attached=false;
    try {
        // Do not follow a symlink revealed underneath the detached bind.
        Fd destination(open(target.c_str(),O_PATH|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC));
        sysok(destination.n,"pin storage directory");
        sysok(fstat(destination.n,&st),"inspect storage directory");
        need(st.st_uid==0 && !(st.st_mode&0022),"unsafe storage directory");
#ifdef FLUX_RECOVERY_TEST
        if(getenv("FLUX_STORAGE_FAIL_BIND"))fail("owned storage bind fault");
#endif
        sysok(static_cast<int>(syscall(SYS_move_mount,replacement.n,"",destination.n,"",move_from_empty|move_to_empty)),"attach current guest storage");
        attached=true;
        Fd current(open(target.c_str(),O_PATH|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC));
        need(identity(current.n)==fresh_id,"replacement storage verification failed");
        fprintf(stderr,"flux-mntns: reconnected guest shared storage\n");
    } catch(...) {
        if(attached && umount2(target.c_str(),MNT_DETACH|UMOUNT_NOFOLLOW))
            fail("storage verification failed; cannot detach replacement");
        // Preserve the old disconnected binding on ordinary syscall failure.
        // This is not a crash-atomic transaction across the two mount syscalls.
        if(!disconnected)throw;
        Fd destination(open(target.c_str(),O_PATH|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC));
        if(destination.n<0 || syscall(SYS_move_mount,rollback.n,"",destination.n,"",move_from_empty|move_to_empty))
            fail("storage recovery failed and old binding could not be restored");
        throw;
    }
}
