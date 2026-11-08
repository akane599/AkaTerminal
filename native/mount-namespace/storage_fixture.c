// Disposable, minimal FUSE server. Never used by the application.
#define _GNU_SOURCE
#include <linux/fuse.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <stdlib.h>
static void attr(struct fuse_attr *a, uint64_t ino) {
    a->ino=ino; a->mode=(ino==1 ? S_IFDIR|0755 : S_IFREG|0644);
    a->nlink=ino==1?2:1; a->size=ino==1?0:6; a->blksize=4096;
}
int main(int argc,char **argv) {
    if(argc!=3) return 2;
    int fd=open("/dev/fuse",O_RDWR|O_CLOEXEC); if(fd<0){perror("fuse");return 3;}
    char opts[160];snprintf(opts,sizeof(opts),"fd=%d,rootmode=40000,user_id=0,group_id=0",fd);
    if(mount("owned-storage",argv[1],"fuse",MS_NOSUID|MS_NODEV,opts)){perror("mount");return 4;}
    printf("READY %d\n",getpid());fflush(stdout);
    char in[131072],out[131072];
    for(;;){
        ssize_t n=read(fd,in,sizeof(in)); if(n<0&&errno==EINTR)continue;if(n<=0)break;
        struct fuse_in_header *h=(void*)in; struct fuse_out_header *r=(void*)out;
        memset(out,0,sizeof(out));r->unique=h->unique;r->len=sizeof(*r);
        void *body=out+sizeof(*r);
        switch(h->opcode){
        case FUSE_INIT:{struct fuse_init_out *v=body;v->major=7;v->minor=23;v->max_write=4096;v->max_background=4;v->congestion_threshold=3;r->len+=sizeof(*v);break;}
        case FUSE_GETATTR:{struct fuse_attr_out *v=body;v->attr_valid=3600;attr(&v->attr,h->nodeid);r->len+=sizeof(*v);break;}
        case FUSE_LOOKUP:{if(strcmp(in+sizeof(*h),"marker")){r->error=-ENOENT;break;}struct fuse_entry_out *v=body;v->nodeid=2;v->generation=1;v->attr_valid=3600;v->entry_valid=3600;attr(&v->attr,2);r->len+=sizeof(*v);break;}
        case FUSE_OPEN: case FUSE_OPENDIR:{struct fuse_open_out *v=body;v->fh=1;r->len+=sizeof(*v);break;}
        case FUSE_READ:{struct fuse_read_in *v=(void*)(in+sizeof(*h));size_t len=strlen(argv[2]);if(v->offset<len){len-=v->offset;if(len>v->size)len=v->size;memcpy(body,argv[2]+v->offset,len);r->len+=len;}break;}
        case FUSE_ACCESS:case FUSE_RELEASE:case FUSE_RELEASEDIR:case FUSE_FLUSH:break;
        case FUSE_STATFS:{struct fuse_statfs_out *v=body;v->st.bsize=4096;v->st.frsize=4096;v->st.namelen=255;r->len+=sizeof(*v);break;}
        case FUSE_FORGET:case FUSE_BATCH_FORGET:continue;
        default:r->error=-ENOSYS;break;
        }
        if(write(fd,out,r->len)!=(ssize_t)r->len)break;
    }
    close(fd);return 0;
}
