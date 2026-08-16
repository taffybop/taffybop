/*
 * Trusted staged-Tesseract runtime gate for Darwin evidence launches.
 *
 * DYLD loads this frozen helper with the exact staged Tesseract image.  Its
 * constructor emits one nonce-bound record and stops the same PID after dyld
 * has mapped the launch closure but before Tesseract main executes.  The
 * broker must verify the fixed record, WSTOPPED state, executable identity,
 * and complete mapped-image projection before SIGCONT.  Absence, malformed
 * authority, or a failed stop is process-fatal; there is no permissive path.
 */

#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

#define RUNTIME_GATE_ACK_BYTES 56

static void put_u64_be(unsigned char *target, uint64_t value) {
    for (int index = 7; index >= 0; --index) {
        target[index] = (unsigned char)(value & 0xffU);
        value >>= 8;
    }
}

static int hex_nibble(char value) {
    if (value >= '0' && value <= '9') {
        return value - '0';
    }
    if (value >= 'a' && value <= 'f') {
        return value - 'a' + 10;
    }
    return -1;
}

static int parse_descriptor(const char *value) {
    if (value == NULL || *value == '\0') {
        return -1;
    }
    int result = 0;
    for (const char *cursor = value; *cursor != '\0'; ++cursor) {
        if (*cursor < '0' || *cursor > '9' || result > 100000) {
            return -1;
        }
        result = result * 10 + (*cursor - '0');
    }
    return result >= 3 ? result : -1;
}

static int write_exact(int descriptor, const unsigned char *body, size_t size) {
    size_t offset = 0;
    while (offset < size) {
        ssize_t written = write(descriptor, body + offset, size - offset);
        if (written < 0 && errno == EINTR) {
            continue;
        }
        if (written <= 0) {
            return -1;
        }
        offset += (size_t)written;
    }
    return 0;
}

__attribute__((constructor))
static void parser_tesseract_runtime_gate(void) {
    const char *descriptor_text = getenv("PARSER_TESSERACT_RUNTIME_GATE_FD");
    const char *nonce_text = getenv("PARSER_TESSERACT_RUNTIME_GATE_NONCE");
    if (descriptor_text == NULL && nonce_text == NULL) {
        return;
    }
    int descriptor = parse_descriptor(descriptor_text);
    if (descriptor < 0 || nonce_text == NULL) {
        _exit(125);
    }
    unsigned char record[RUNTIME_GATE_ACK_BYTES] = {
        'R', 'T', 'G', 'A', 'T', 'E', '1', '!'
    };
    for (int index = 0; index < 32; ++index) {
        int high = hex_nibble(nonce_text[index * 2]);
        int low = hex_nibble(nonce_text[index * 2 + 1]);
        if (high < 0 || low < 0) {
            _exit(125);
        }
        record[24 + index] = (unsigned char)((high << 4) | low);
    }
    if (nonce_text[64] != '\0') {
        _exit(125);
    }
    struct timespec observed;
    if (clock_gettime(CLOCK_MONOTONIC, &observed) != 0) {
        _exit(125);
    }
    uint64_t observed_ns =
        (uint64_t)observed.tv_sec * 1000000000ULL +
        (uint64_t)observed.tv_nsec;
    put_u64_be(record + 8, (uint64_t)getpid());
    put_u64_be(record + 16, observed_ns);
    if (
        observed_ns == 0 ||
        write_exact(descriptor, record, sizeof(record)) != 0 ||
        close(descriptor) != 0 ||
        kill(getpid(), SIGSTOP) != 0
    ) {
        _exit(125);
    }
}

