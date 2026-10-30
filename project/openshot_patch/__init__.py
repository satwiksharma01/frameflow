"""OpenShot's `classes` package, as patched by Frameflow (GPLv3, like OpenShot).

The launcher imports this package before it creates any window, with
libopenshot already loaded. With FRAMEFLOW_RUN set to a Python file, that file
runs here instead of the editor - which gives Frameflow OpenShot's own engine
without a window.
"""
import os

if os.environ.get("FRAMEFLOW_RUN"):
    import runpy
    import sys
    import traceback

    code = 0
    script = os.environ.pop("FRAMEFLOW_RUN")
    sys.argv = [script] + sys.argv[1:]
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    # Skip the editor's own start-up, which would follow this import.
    os._exit(code)
