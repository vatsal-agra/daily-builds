/* The allocators qsim can replay a trace against. */
#ifndef QUARRY_MODELS_H
#define QUARRY_MODELS_H
#include <stddef.h>

typedef struct Model {
    const char *name;
    const char *desc;
    int    (*init)(void);
    void   (*fini)(void);
    void  *(*alloc)(size_t n, int zero);
    void  *(*aligned)(size_t align, size_t n);
    void   (*release)(void *p);
    void  *(*resize)(void *p, size_t old_n, size_t n);
    size_t (*footprint)(void);       /* bytes currently held from the OS */
    size_t (*peak)(void);            /* allocator-tracked peak, 0 if it does not know */
    void   (*trim)(void);            /* give back whatever it can (may be NULL) */
} Model;

extern const Model *const MODELS[];  /* NULL terminated */
const Model *model_by_name(const char *name);

#endif
