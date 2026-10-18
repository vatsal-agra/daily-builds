#include <stdio.h>
#include "mathx.h"
#include "strx.h"
#include "version.h"
int main(void) {
    printf("app %s: 7^2=%d 3^3=%d vowels=%d\n", APP_VERSION, square(7), cube(3), vowels("mortise"));
    return 0;
}
