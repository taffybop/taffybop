/*
 * Safe native process-birth denial probe for the supervised Darwin worker.
 *
 * A successful vfork child must not return through libffi or Python.  This
 * helper therefore exits inside native code before returning to its caller;
 * the parent reports zero so the Python supervisor can terminate the invalid
 * attempt.  The accepted path is an EPERM/EAGAIN result for every operation.
 */

#include <errno.h>
#include <spawn.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

enum parser_birth_probe_operation {
    PARSER_PROBE_FORK = 1,
    PARSER_PROBE_VFORK = 2,
    PARSER_PROBE_POSIX_SPAWN = 3,
};

static int import_time_fork_errno = EINPROGRESS;

static int wait_for_exact_child(pid_t pid) {
    int status = 0;
    pid_t result;
    do {
        result = waitpid(pid, &status, 0);
    } while (result < 0 && errno == EINTR);
    if (result != pid) {
        return errno != 0 ? errno : ECHILD;
    }
    return 0;
}

__attribute__((constructor))
static void parser_probe_import_time_fork(void) {
    errno = 0;
    pid_t pid = fork();
    if (pid < 0) {
        import_time_fork_errno = errno != 0 ? errno : EIO;
        return;
    }
    if (pid == 0) {
        _exit(126);
    }
    import_time_fork_errno = wait_for_exact_child(pid);
}

__attribute__((visibility("default")))
int parser_probe_import_time_fork_errno(void) {
    return import_time_fork_errno;
}

__attribute__((visibility("default")))
int parser_probe_process_birth(int operation, const char *spawn_path) {
    pid_t pid = -1;

    errno = 0;
    if (operation == PARSER_PROBE_FORK) {
        pid = fork();
    } else if (operation == PARSER_PROBE_VFORK) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
        pid = vfork();
#pragma clang diagnostic pop
    } else if (operation == PARSER_PROBE_POSIX_SPAWN) {
        if (spawn_path == NULL || spawn_path[0] != '/') {
            return EINVAL;
        }
        char *const argv[] = {(char *)spawn_path, NULL};
        char *const envp[] = {(char *)"PATH=/usr/bin:/bin", NULL};
        int result = posix_spawn(&pid, spawn_path, NULL, NULL, argv, envp);
        if (result != 0) {
            return result;
        }
    } else {
        return EINVAL;
    }

    if (pid < 0) {
        return errno != 0 ? errno : EIO;
    }
    if (pid == 0) {
        _exit(127);
    }
    return wait_for_exact_child(pid);
}
