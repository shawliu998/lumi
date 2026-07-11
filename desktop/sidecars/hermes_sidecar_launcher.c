#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
  (void)argc;
  const char *runtime_dir = getenv("HERMES_SIDECAR_RUNTIME_DIR");
  if (runtime_dir == NULL || runtime_dir[0] == '\0') {
    fputs("HERMES_SIDECAR_RUNTIME_DIR is required\n", stderr);
    return 127;
  }

  char executable[PATH_MAX];
  int written = snprintf(executable, sizeof(executable), "%s/hermes-sidecar", runtime_dir);
  if (written < 0 || (size_t)written >= sizeof(executable)) {
    fputs("Lumi sidecar runtime path is too long\n", stderr);
    return 127;
  }

  argv[0] = executable;
  execv(executable, argv);
  fprintf(stderr, "failed to exec Lumi sidecar runtime: %s\n", strerror(errno));
  return 127;
}
