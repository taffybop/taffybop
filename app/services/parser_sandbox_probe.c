#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define LAT_US02_SANDBOX_PROBE_ABI 2

enum lat_us02_probe_stage {
    LAT_US02_STAGE_NONE = 0,
    LAT_US02_STAGE_FCHDIR = 1,
    LAT_US02_STAGE_OPEN = 2,
    LAT_US02_STAGE_WRITE = 3,
    LAT_US02_STAGE_FSYNC = 4,
    LAT_US02_STAGE_READ = 5,
    LAT_US02_STAGE_RENAME = 6,
    LAT_US02_STAGE_UNLINK = 7,
    LAT_US02_STAGE_MKDIR = 8,
    LAT_US02_STAGE_SOCKET = 9,
    LAT_US02_STAGE_CONNECT = 10,
    LAT_US02_STAGE_SENDTO = 11,
    LAT_US02_STAGE_BIND = 12,
    LAT_US02_STAGE_LISTEN = 13,
    LAT_US02_STAGE_RESTORE_CWD = 14
};

enum lat_us02_path_operation {
    LAT_US02_PATH_OPEN = 1,
    LAT_US02_PATH_RENAME = 2,
    LAT_US02_PATH_UNLINK = 3,
    LAT_US02_PATH_MKDIR = 4,
    LAT_US02_PATH_READ = 5,
    LAT_US02_PATH_SCRATCH_ROUNDTRIP = 6
};

enum lat_us02_network_operation {
    LAT_US02_NETWORK_CONNECT = 1,
    LAT_US02_NETWORK_SENDTO = 2,
    LAT_US02_NETWORK_BIND_LISTEN = 3
};

struct lat_us02_probe_result {
    int32_t abi_version;
    int32_t operation;
    int32_t terminal_stage;
    int32_t raw_errno;
    int64_t syscall_return;
    int64_t bytes_sent;
    int64_t bytes_received;
    int32_t cwd_restore_return;
    int32_t cwd_restore_errno;
};

_Static_assert(sizeof(struct lat_us02_probe_result) == 48, "probe result ABI size");
_Static_assert(offsetof(struct lat_us02_probe_result, abi_version) == 0, "probe ABI offset");
_Static_assert(offsetof(struct lat_us02_probe_result, operation) == 4, "probe operation offset");
_Static_assert(offsetof(struct lat_us02_probe_result, terminal_stage) == 8, "probe stage offset");
_Static_assert(offsetof(struct lat_us02_probe_result, raw_errno) == 12, "probe errno offset");
_Static_assert(offsetof(struct lat_us02_probe_result, syscall_return) == 16, "probe return offset");
_Static_assert(offsetof(struct lat_us02_probe_result, bytes_sent) == 24, "probe sent offset");
_Static_assert(offsetof(struct lat_us02_probe_result, bytes_received) == 32, "probe received offset");
_Static_assert(offsetof(struct lat_us02_probe_result, cwd_restore_return) == 40, "probe cwd return offset");
_Static_assert(offsetof(struct lat_us02_probe_result, cwd_restore_errno) == 44, "probe cwd errno offset");

static void lat_us02_initialize_result(
    struct lat_us02_probe_result *result,
    int operation
) {
    memset(result, 0, sizeof(*result));
    result->abi_version = LAT_US02_SANDBOX_PROBE_ABI;
    result->operation = operation;
    result->terminal_stage = LAT_US02_STAGE_NONE;
    result->syscall_return = -1;
    result->cwd_restore_return = 0;
}

static void lat_us02_failure(
    struct lat_us02_probe_result *result,
    int stage,
    int64_t syscall_return
) {
    result->terminal_stage = stage;
    result->syscall_return = syscall_return;
    result->raw_errno = errno;
}

static int lat_us02_restore_cwd(
    int cwd_fd,
    struct lat_us02_probe_result *result
) {
    int saved_errno = errno;
    errno = 0;
    int restored = fchdir(cwd_fd);
    int restore_errno = errno;
    close(cwd_fd);
    result->cwd_restore_return = restored;
    result->cwd_restore_errno = restore_errno;
    if (restored != 0) {
        result->terminal_stage = LAT_US02_STAGE_RESTORE_CWD;
        result->syscall_return = restored;
        result->raw_errno = restore_errno;
        return -1;
    }
    errno = saved_errno;
    return 0;
}

static int lat_us02_return_result(
    const struct lat_us02_probe_result *result
) {
    /* Successful cleanup syscalls may clobber errno.  The fixed ABI exposes
     * the operation errno both in-band and as the top-level ctypes errno, so
     * restore it explicitly at the sole successful API return boundary. */
    errno = result->raw_errno;
    return 0;
}

__attribute__((visibility("default")))
int lat_us02_sandbox_probe_path(
    int operation,
    int held_directory_fd,
    const char *primary_relative_path,
    const char *secondary_relative_path,
    int open_flags,
    mode_t create_mode,
    const uint8_t *payload,
    size_t payload_size,
    struct lat_us02_probe_result *result
) {
    if (result == NULL || primary_relative_path == NULL ||
        primary_relative_path[0] == '\0' || strchr(primary_relative_path, '/') != NULL ||
        strcmp(primary_relative_path, ".") == 0 ||
        strcmp(primary_relative_path, "..") == 0 ||
        (secondary_relative_path != NULL &&
         (secondary_relative_path[0] == '\0' ||
          strchr(secondary_relative_path, '/') != NULL ||
          strcmp(secondary_relative_path, ".") == 0 ||
          strcmp(secondary_relative_path, "..") == 0)) ||
        (payload_size > 0 && payload == NULL)) {
        errno = EINVAL;
        return -1;
    }
    lat_us02_initialize_result(result, operation);
    int cwd_fd = open(".", O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (cwd_fd < 0) {
        lat_us02_failure(result, LAT_US02_STAGE_FCHDIR, -1);
        return lat_us02_return_result(result);
    }
    errno = 0;
    if (fchdir(held_directory_fd) != 0) {
        lat_us02_failure(result, LAT_US02_STAGE_FCHDIR, -1);
        (void)lat_us02_restore_cwd(cwd_fd, result);
        return lat_us02_return_result(result);
    }

    int descriptor = -1;
    ssize_t value = -1;
    switch (operation) {
        case LAT_US02_PATH_OPEN:
            errno = 0;
            descriptor = open(primary_relative_path, open_flags, create_mode);
            if (descriptor < 0) {
                lat_us02_failure(result, LAT_US02_STAGE_OPEN, descriptor);
            } else {
                result->terminal_stage = LAT_US02_STAGE_OPEN;
                result->syscall_return = descriptor;
                close(descriptor);
            }
            break;
        case LAT_US02_PATH_RENAME:
            if (secondary_relative_path == NULL) {
                errno = EINVAL;
                lat_us02_failure(result, LAT_US02_STAGE_RENAME, -1);
                break;
            }
            errno = 0;
            value = rename(primary_relative_path, secondary_relative_path);
            result->terminal_stage = LAT_US02_STAGE_RENAME;
            result->syscall_return = value;
            result->raw_errno = value < 0 ? errno : 0;
            break;
        case LAT_US02_PATH_UNLINK:
            errno = 0;
            value = unlink(primary_relative_path);
            result->terminal_stage = LAT_US02_STAGE_UNLINK;
            result->syscall_return = value;
            result->raw_errno = value < 0 ? errno : 0;
            break;
        case LAT_US02_PATH_MKDIR:
            errno = 0;
            value = mkdir(primary_relative_path, create_mode);
            result->terminal_stage = LAT_US02_STAGE_MKDIR;
            result->syscall_return = value;
            result->raw_errno = value < 0 ? errno : 0;
            break;
        case LAT_US02_PATH_READ:
            errno = 0;
            descriptor = open(primary_relative_path, open_flags, create_mode);
            if (descriptor < 0) {
                lat_us02_failure(result, LAT_US02_STAGE_OPEN, descriptor);
                break;
            }
            result->bytes_received = 0;
            uint8_t buffer[16384];
            for (;;) {
                errno = 0;
                value = read(descriptor, buffer, sizeof(buffer));
                if (value < 0) {
                    lat_us02_failure(result, LAT_US02_STAGE_READ, value);
                    break;
                }
                if (value == 0) {
                    result->terminal_stage = LAT_US02_STAGE_READ;
                    result->syscall_return = result->bytes_received;
                    result->raw_errno = 0;
                    break;
                }
                result->bytes_received += value;
            }
            close(descriptor);
            break;
        case LAT_US02_PATH_SCRATCH_ROUNDTRIP:
            errno = 0;
            descriptor = open(primary_relative_path, open_flags, create_mode);
            if (descriptor < 0) {
                lat_us02_failure(result, LAT_US02_STAGE_OPEN, descriptor);
                break;
            }
            errno = 0;
            value = write(descriptor, payload, payload_size);
            if (value < 0 || (size_t)value != payload_size) {
                lat_us02_failure(result, LAT_US02_STAGE_WRITE, value);
                close(descriptor);
                break;
            }
            result->bytes_sent = value;
            errno = 0;
            if (fsync(descriptor) != 0) {
                lat_us02_failure(result, LAT_US02_STAGE_FSYNC, -1);
                close(descriptor);
                break;
            }
            if (lseek(descriptor, 0, SEEK_SET) != 0) {
                lat_us02_failure(result, LAT_US02_STAGE_READ, -1);
                close(descriptor);
                break;
            }
            result->bytes_received = 0;
            uint8_t roundtrip[256];
            if (payload_size > sizeof(roundtrip)) {
                errno = EOVERFLOW;
                lat_us02_failure(result, LAT_US02_STAGE_READ, -1);
                close(descriptor);
                break;
            }
            errno = 0;
            value = read(descriptor, roundtrip, payload_size);
            if (value < 0 || (size_t)value != payload_size ||
                memcmp(roundtrip, payload, payload_size) != 0) {
                if (value >= 0) errno = EIO;
                lat_us02_failure(result, LAT_US02_STAGE_READ, value);
                close(descriptor);
                break;
            }
            result->bytes_received = value;
            close(descriptor);
            errno = 0;
            value = unlink(primary_relative_path);
            result->terminal_stage = LAT_US02_STAGE_UNLINK;
            result->syscall_return = value;
            result->raw_errno = value < 0 ? errno : 0;
            break;
        default:
            errno = EINVAL;
            lat_us02_failure(result, LAT_US02_STAGE_NONE, -1);
            break;
    }
    (void)lat_us02_restore_cwd(cwd_fd, result);
    return lat_us02_return_result(result);
}

__attribute__((visibility("default")))
int lat_us02_sandbox_probe_network(
    int operation,
    int domain,
    int socket_type,
    int protocol,
    int held_directory_fd,
    const void *sockaddr_bytes,
    uint32_t sockaddr_size,
    const uint8_t *payload,
    size_t payload_size,
    struct lat_us02_probe_result *result
) {
    if (result == NULL || sockaddr_bytes == NULL || sockaddr_size == 0 ||
        (domain == AF_UNIX && held_directory_fd < 0) ||
        (domain != AF_UNIX && held_directory_fd != -1) ||
        (payload_size > 0 && payload == NULL)) {
        errno = EINVAL;
        return -1;
    }
    lat_us02_initialize_result(result, operation);
    int cwd_fd = -1;
    if (domain == AF_UNIX) {
        cwd_fd = open(
            ".",
            O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW
        );
        if (cwd_fd < 0) {
            lat_us02_failure(result, LAT_US02_STAGE_FCHDIR, -1);
            return lat_us02_return_result(result);
        }
        errno = 0;
        if (fchdir(held_directory_fd) != 0) {
            lat_us02_failure(result, LAT_US02_STAGE_FCHDIR, -1);
            (void)lat_us02_restore_cwd(cwd_fd, result);
            return lat_us02_return_result(result);
        }
    }
    errno = 0;
    int descriptor = socket(domain, socket_type, protocol);
    if (descriptor < 0) {
        lat_us02_failure(result, LAT_US02_STAGE_SOCKET, descriptor);
        if (cwd_fd >= 0) {
            (void)lat_us02_restore_cwd(cwd_fd, result);
        }
        return lat_us02_return_result(result);
    }
    if (fcntl(descriptor, F_SETFD, FD_CLOEXEC) != 0) {
        lat_us02_failure(result, LAT_US02_STAGE_SOCKET, -1);
        close(descriptor);
        if (cwd_fd >= 0) {
            (void)lat_us02_restore_cwd(cwd_fd, result);
        }
        return lat_us02_return_result(result);
    }
    ssize_t value = -1;
    switch (operation) {
        case LAT_US02_NETWORK_CONNECT:
            errno = 0;
            value = connect(
                descriptor,
                (const struct sockaddr *)sockaddr_bytes,
                (socklen_t)sockaddr_size
            );
            result->terminal_stage = LAT_US02_STAGE_CONNECT;
            result->syscall_return = value;
            result->raw_errno = value < 0 ? errno : 0;
            break;
        case LAT_US02_NETWORK_SENDTO:
            errno = 0;
            value = sendto(
                descriptor,
                payload,
                payload_size,
                0,
                (const struct sockaddr *)sockaddr_bytes,
                (socklen_t)sockaddr_size
            );
            result->terminal_stage = LAT_US02_STAGE_SENDTO;
            result->syscall_return = value;
            result->raw_errno = value < 0 ? errno : 0;
            result->bytes_sent = value > 0 ? value : 0;
            break;
        case LAT_US02_NETWORK_BIND_LISTEN:
            errno = 0;
            value = bind(
                descriptor,
                (const struct sockaddr *)sockaddr_bytes,
                (socklen_t)sockaddr_size
            );
            if (value < 0) {
                lat_us02_failure(result, LAT_US02_STAGE_BIND, value);
                break;
            }
            errno = 0;
            value = listen(descriptor, 1);
            result->terminal_stage = LAT_US02_STAGE_LISTEN;
            result->syscall_return = value;
            result->raw_errno = value < 0 ? errno : 0;
            break;
        default:
            errno = EINVAL;
            lat_us02_failure(result, LAT_US02_STAGE_NONE, -1);
            break;
    }
    close(descriptor);
    if (cwd_fd >= 0) {
        (void)lat_us02_restore_cwd(cwd_fd, result);
    }
    return lat_us02_return_result(result);
}
