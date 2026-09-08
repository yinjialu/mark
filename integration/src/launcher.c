// Native Apple Silicon entry point; the packaged script carries local paths.
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    char executable[PATH_MAX], script[PATH_MAX];
    uint32_t size = sizeof executable;
    if (_NSGetExecutablePath(executable, &size) != 0) {
        fprintf(stderr, "mark: launcher path is too long\n");
        return 1;
    }
    char *slash = strrchr(executable, '/');
    if (!slash) return 1;
    *slash = '\0';
    int length = snprintf(script, sizeof script, "%s/../Resources/launch.sh", executable);
    if (length < 0 || (size_t)length >= sizeof script) return 1;
    execl("/bin/sh", "sh", script, (char *)NULL);
    perror("mark: cannot start launcher");
    return 1;
}
