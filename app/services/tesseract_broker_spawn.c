/*
 * Sole-thread Darwin broker spawn boundary.
 *
 * Calling libc fork(3) would run process-wide pthread_atfork callbacks before
 * this code can revoke process-birth authority in the child.  This helper
 * therefore enters the kernel fork syscall directly.  The child installs and
 * verifies hard RLIMIT_NPROC=(0,0), while the inherited signal mask is still
 * blocked, before returning to its single Python caller.  From that point the
 * child can arrange fixed descriptors and enter the byte-bound exec guard,
 * but it can no longer create an omitted descendant.
 */

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <time.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <unistd.h>

#define NPROC_ACK_BYTES 40
#define GUARD_EXEC_ERROR_BYTES 24

static void put_u64_be(unsigned char *target, uint64_t value) {
    for (int index = 7; index >= 0; --index) {
        target[index] = (unsigned char)(value & 0xffU);
        value >>= 8;
    }
}

static int write_child_limit_ack(
    int descriptor,
    uint64_t child_pid,
    uint64_t applied_monotonic_ns,
    uint64_t soft_limit,
    uint64_t hard_limit
) {
    static const unsigned char magic[8] = {
        'P', 'N', '0', 'A', 'C', 'K', '1', '!'
    };
    unsigned char record[NPROC_ACK_BYTES];
    for (int index = 0; index < 8; ++index) {
        record[index] = magic[index];
    }
    put_u64_be(record + 8, child_pid);
    put_u64_be(record + 16, applied_monotonic_ns);
    put_u64_be(record + 24, soft_limit);
    put_u64_be(record + 32, hard_limit);
    size_t offset = 0;
    while (offset < sizeof(record)) {
        ssize_t written = write(
            descriptor,
            record + offset,
            sizeof(record) - offset
        );
        if (written < 0 && errno == EINTR) {
            continue;
        }
        if (written <= 0) {
            return errno != 0 ? errno : EIO;
        }
        offset += (size_t)written;
    }
    return 0;
}

static int write_guard_exec_error(int descriptor, uint64_t pid, int error) {
    static const unsigned char magic[8] = {
        'G', 'E', 'X', 'E', 'C', '1', '!', '!'
    };
    unsigned char record[GUARD_EXEC_ERROR_BYTES];
    for (int index = 0; index < 8; ++index) {
        record[index] = magic[index];
    }
    put_u64_be(record + 8, pid);
    put_u64_be(record + 16, (uint64_t)(error > 0 ? error : EIO));
    size_t offset = 0;
    while (offset < sizeof(record)) {
        ssize_t written = write(
            descriptor,
            record + offset,
            sizeof(record) - offset
        );
        if (written < 0 && errno == EINTR) {
            continue;
        }
        if (written <= 0) {
            return errno != 0 ? errno : EIO;
        }
        offset += (size_t)written;
    }
    return 0;
}

/* Darwin's private libc syscall veneer: unlike fork(3), this does not run
 * process-wide pthread_atfork callbacks, but it does normalize the kernel's
 * dual-register fork return ABI into parent-PID/zero semantics.  Its exact
 * symbol and the compiled helper bytes are frozen by the launch receipt. */
extern pid_t __fork(void);

static volatile sig_atomic_t adversarial_child_atfork_calls = 0;

static void adversarial_child_atfork(void) {
    adversarial_child_atfork_calls++;
}

__attribute__((visibility("default")))
int parser_broker_install_adversarial_atfork_probe(void) {
    return pthread_atfork(NULL, NULL, adversarial_child_atfork);
}

__attribute__((visibility("default")))
int parser_broker_adversarial_atfork_child_calls(void) {
    return (int)adversarial_child_atfork_calls;
}

static int required_signals_blocked(void) {
    sigset_t current;
    int result = pthread_sigmask(SIG_SETMASK, NULL, &current);
    if (result != 0) {
        return result;
    }
    if (sigismember(&current, SIGTERM) != 1 ||
        sigismember(&current, SIGHUP) != 1) {
        return EPERM;
    }
    return 0;
}

__attribute__((visibility("default")))
int64_t parser_broker_raw_fork_exec_child_denied(
    int *child_limit_errno,
    uint64_t *child_limit_applied_monotonic_ns,
    int pre_python_release_fd,
    int child_limit_ack_fd,
    int child_state_ack_fd,
    int guard_exec_error_fd,
    const char *guard_python_path,
    char *const guard_argv[],
    char *const guard_envp[],
    const int guard_inherited_fds[],
    size_t guard_inherited_fd_count
) {
    if (child_limit_errno == NULL || child_limit_applied_monotonic_ns == NULL ||
        pre_python_release_fd < 0 || child_limit_ack_fd < 0 ||
        child_state_ack_fd < 0 || guard_exec_error_fd < 0 ||
        guard_python_path == NULL || guard_argv == NULL ||
        guard_envp == NULL || guard_inherited_fds == NULL ||
        guard_inherited_fd_count == 0 || guard_inherited_fd_count > 16) {
        errno = EINVAL;
        return -1;
    }
    *child_limit_errno = 0;
    *child_limit_applied_monotonic_ns = 0;
    int mask_error = required_signals_blocked();
    if (mask_error != 0) {
        errno = mask_error;
        return -1;
    }

    errno = 0;
    pid_t pid = __fork();
    if (pid < 0) {
        return -1;
    }
    if (pid == 0) {
#if defined(PARSER_BROKER_TEST_CHILD_ACK_DELAY_NS)
        struct timespec delay_start;
        struct timespec delay_now;
        if (clock_gettime(CLOCK_MONOTONIC, &delay_start) != 0) {
            _exit(125);
        }
        uint64_t delay_start_ns =
            (uint64_t)delay_start.tv_sec * 1000000000ULL +
            (uint64_t)delay_start.tv_nsec;
        for (;;) {
            if (clock_gettime(CLOCK_MONOTONIC, &delay_now) != 0) {
                _exit(125);
            }
            uint64_t delay_now_ns =
                (uint64_t)delay_now.tv_sec * 1000000000ULL +
                (uint64_t)delay_now.tv_nsec;
            if (delay_now_ns - delay_start_ns >=
                (uint64_t)PARSER_BROKER_TEST_CHILD_ACK_DELAY_NS) {
                break;
            }
        }
#endif
        struct rlimit denied = {0, 0};
        struct rlimit observed = {RLIM_INFINITY, RLIM_INFINITY};
        if (setrlimit(RLIMIT_NPROC, &denied) != 0 ||
            getrlimit(RLIMIT_NPROC, &observed) != 0 ||
            observed.rlim_cur != 0 || observed.rlim_max != 0) {
            *child_limit_errno = errno != 0 ? errno : EIO;
            _exit(125);
        }
        struct timespec applied;
        if (clock_gettime(CLOCK_MONOTONIC, &applied) != 0 ||
            applied.tv_sec < 0 || applied.tv_nsec < 0 ||
            applied.tv_nsec >= 1000000000L) {
            _exit(125);
        }
        *child_limit_applied_monotonic_ns =
            (uint64_t)applied.tv_sec * 1000000000ULL +
            (uint64_t)applied.tv_nsec;
        if (*child_limit_applied_monotonic_ns == 0) {
            _exit(125);
        }
        mask_error = required_signals_blocked();
        if (mask_error != 0) {
            *child_limit_errno = mask_error;
            _exit(125);
        }
        int ack_error = write_child_limit_ack(
            child_limit_ack_fd,
            (uint64_t)getpid(),
            *child_limit_applied_monotonic_ns,
            (uint64_t)observed.rlim_cur,
            (uint64_t)observed.rlim_max
        );
        int state_ack_error = write_child_limit_ack(
            child_state_ack_fd,
            (uint64_t)getpid(),
            *child_limit_applied_monotonic_ns,
            (uint64_t)observed.rlim_cur,
            (uint64_t)observed.rlim_max
        );
        if (ack_error != 0 || state_ack_error != 0 ||
            close(child_limit_ack_fd) != 0 ||
            close(child_state_ack_fd) != 0) {
            *child_limit_errno = ack_error != 0 ? ack_error : errno;
            _exit(125);
        }
        unsigned char release = 0;
        ssize_t read_result;
        do {
            read_result = read(pre_python_release_fd, &release, 1);
        } while (read_result < 0 && errno == EINTR);
        if (read_result != 1 || release != (unsigned char)'N') {
            (void)write_guard_exec_error(
                guard_exec_error_fd,
                (uint64_t)getpid(),
                errno != 0 ? errno : EPROTO
            );
            _exit(125);
        }
        for (size_t index = 0; index < guard_inherited_fd_count; ++index) {
            int descriptor = guard_inherited_fds[index];
            int flags = fcntl(descriptor, F_GETFD);
            if (descriptor < 0 || flags < 0 ||
                fcntl(descriptor, F_SETFD, flags & ~FD_CLOEXEC) != 0) {
                (void)write_guard_exec_error(
                    guard_exec_error_fd,
                    (uint64_t)getpid(),
                    errno != 0 ? errno : EBADF
                );
                _exit(125);
            }
        }
        execve(guard_python_path, guard_argv, guard_envp);
        int exec_error = errno != 0 ? errno : EIO;
        (void)write_guard_exec_error(
            guard_exec_error_fd,
            (uint64_t)getpid(),
            exec_error
        );
        _exit(127);
    }
    return (int64_t)pid;
}

/* Test-only ABI for the frozen native denial adversarial.  Production never
 * resolves this symbol; unlike the exec handoff above it deliberately returns
 * to its tiny probe caller so the test can verify NPROC and atfork outcomes. */
__attribute__((visibility("default")))
int64_t parser_broker_raw_fork_probe_child_denied(
    int *child_limit_errno,
    uint64_t *child_limit_applied_monotonic_ns,
    int pre_python_release_fd,
    int child_limit_ack_fd
) {
    if (child_limit_errno == NULL || child_limit_applied_monotonic_ns == NULL ||
        pre_python_release_fd < 0 || child_limit_ack_fd < 0) {
        errno = EINVAL;
        return -1;
    }
    *child_limit_errno = 0;
    *child_limit_applied_monotonic_ns = 0;
    int mask_error = required_signals_blocked();
    if (mask_error != 0) {
        errno = mask_error;
        return -1;
    }
    pid_t pid = __fork();
    if (pid < 0) {
        return -1;
    }
    if (pid == 0) {
#if defined(PARSER_BROKER_TEST_CHILD_ACK_DELAY_NS)
        struct timespec delay_start;
        struct timespec delay_now;
        if (clock_gettime(CLOCK_MONOTONIC, &delay_start) != 0) {
            _exit(125);
        }
        uint64_t delay_start_ns =
            (uint64_t)delay_start.tv_sec * 1000000000ULL +
            (uint64_t)delay_start.tv_nsec;
        for (;;) {
            if (clock_gettime(CLOCK_MONOTONIC, &delay_now) != 0) {
                _exit(125);
            }
            uint64_t delay_now_ns =
                (uint64_t)delay_now.tv_sec * 1000000000ULL +
                (uint64_t)delay_now.tv_nsec;
            if (delay_now_ns - delay_start_ns >=
                (uint64_t)PARSER_BROKER_TEST_CHILD_ACK_DELAY_NS) {
                break;
            }
        }
#endif
        struct rlimit denied = {0, 0};
        struct rlimit observed = {RLIM_INFINITY, RLIM_INFINITY};
        struct timespec applied;
        if (setrlimit(RLIMIT_NPROC, &denied) != 0 ||
            getrlimit(RLIMIT_NPROC, &observed) != 0 ||
            observed.rlim_cur != 0 || observed.rlim_max != 0 ||
            clock_gettime(CLOCK_MONOTONIC, &applied) != 0 ||
            applied.tv_sec < 0 || applied.tv_nsec < 0 ||
            applied.tv_nsec >= 1000000000L) {
            _exit(125);
        }
        *child_limit_applied_monotonic_ns =
            (uint64_t)applied.tv_sec * 1000000000ULL +
            (uint64_t)applied.tv_nsec;
        int ack_error = write_child_limit_ack(
            child_limit_ack_fd,
            (uint64_t)getpid(),
            *child_limit_applied_monotonic_ns,
            0,
            0
        );
        if (ack_error != 0 || close(child_limit_ack_fd) != 0) {
            _exit(125);
        }
        unsigned char release = 0;
        ssize_t read_result;
        do {
            read_result = read(pre_python_release_fd, &release, 1);
        } while (read_result < 0 && errno == EINTR);
        if (read_result != 1 || release != (unsigned char)'N') {
            _exit(125);
        }
    }
    return (int64_t)pid;
}
