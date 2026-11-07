// Disposable static test program, never packaged in the APK.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    if (!strcmp(argv[1], "--suid-result")) {
        printf("uid=%u euid=%u\n", getuid(), geteuid());
        return getuid() == 1000 && geteuid() == 0 ? 0 : 3;
    }
    if (!strcmp(argv[1], "--suid")) {
        if (setgid(1000) || setuid(1000)) return 4;
        execl("/suid-probe", "/suid-probe", "--suid-result", NULL);
        perror("exec suid fixture"); return 5;
    }
    if (strcmp(argv[1], "--pty")) return 6;
    char path[256];
    int error = ttyname_r(0, path, sizeof(path));
    if (error) { fprintf(stderr, "ttyname: %s\n", strerror(error)); return 7; }
    struct stat fd, named;
    if (fstat(0, &fd) || stat(path, &named) || fd.st_dev != named.st_dev ||
        fd.st_ino != named.st_ino || fd.st_rdev != named.st_rdev) return 8;
    // A guest user must also be able to create a fresh tmux-style PTY.
    if (setgid(1000) || setuid(1000)) return 9;
    int master = posix_openpt(O_RDWR | O_NOCTTY);
    if (master < 0 || grantpt(master) || unlockpt(master)) { perror("guest ptmx"); return 10; }
    char *slave = ptsname(master);
    if (!slave) return 11;
    int peer = open(slave, O_RDWR | O_NOCTTY);
    if (peer < 0) { perror("guest slave"); return 12; }
    dprintf(1, "PTY_OK pid=%d inherited=%s new=%s uid=%u\n", getpid(), path, slave, getuid());
    close(peer); close(master);
    // Parent inspects /proc/PID/root, then gracefully terminates this owned child.
    sleep(15);
    return 0;
}
