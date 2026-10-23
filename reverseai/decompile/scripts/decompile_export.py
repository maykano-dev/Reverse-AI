# Ghidra headless post-script: decompile every function to C and write it out.
# Runs inside Ghidra (PyGhidra or Jython). Globals currentProgram/monitor are
# injected by Ghidra. Output path comes from REVERSEAI_DECOMP_OUT.
# @category ReverseAI
import os

from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

out_path = os.environ.get("REVERSEAI_DECOMP_OUT", "/tmp/reverseai_decomp.c")
max_funcs = int(os.environ.get("REVERSEAI_DECOMP_MAX", "400"))

decomp = DecompInterface()
decomp.openProgram(currentProgram)
mon = monitor if "monitor" in dir() else ConsoleTaskMonitor()

fm = currentProgram.getFunctionManager()
written = 0
with open(out_path, "w") as f:
    f.write("// Decompiled by Ghidra via ReverseAI\n\n")
    for func in fm.getFunctions(True):
        if written >= max_funcs:
            break
        if func.isThunk() or func.isExternal():
            continue
        try:
            res = decomp.decompileFunction(func, 45, mon)
        except Exception:
            continue
        if res is not None and res.decompileCompleted():
            df = res.getDecompiledFunction()
            if df is not None:
                f.write("// --- %s @ %s ---\n" % (func.getName(), func.getEntryPoint()))
                f.write(df.getC())
                f.write("\n\n")
                written += 1

print("ReverseAI: decompiled %d functions -> %s" % (written, out_path))
