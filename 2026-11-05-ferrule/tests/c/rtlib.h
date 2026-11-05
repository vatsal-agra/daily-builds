typedef unsigned long size_t;
long sys_write(int fd, const void *buf, size_t n);
void sys_exit(int code);
size_t rt_strlen(const char *s);
void rt_puts(const char *s);
void rt_putu(unsigned long v);
void rt_putnl(void);
