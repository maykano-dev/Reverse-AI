// Ghidra headless post-script: decompile every function to C and write it out.
// Native Java GhidraScript (Ghidra 12.x dropped Jython; this avoids the PyGhidra
// dependency). currentProgram and monitor are inherited from GhidraScript.
// Output path and cap come from REVERSEAI_DECOMP_OUT / REVERSEAI_DECOMP_MAX.
// @category ReverseAI
import java.io.FileWriter;
import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.decompiler.DecompiledFunction;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.FunctionManager;

public class decompile_export extends GhidraScript {
    @Override
    public void run() throws Exception {
        String outPath = System.getenv("REVERSEAI_DECOMP_OUT");
        if (outPath == null || outPath.isEmpty()) {
            outPath = "/tmp/reverseai_decomp.c";
        }
        int maxFuncs = 400;
        String maxEnv = System.getenv("REVERSEAI_DECOMP_MAX");
        if (maxEnv != null && !maxEnv.isEmpty()) {
            try {
                maxFuncs = Integer.parseInt(maxEnv.trim());
            } catch (NumberFormatException ignored) {
            }
        }

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        FunctionManager fm = currentProgram.getFunctionManager();
        int written = 0;
        PrintWriter f = new PrintWriter(new FileWriter(outPath));
        try {
            f.write("// Decompiled by Ghidra via ReverseAI\n\n");
            FunctionIterator it = fm.getFunctions(true);
            while (it.hasNext() && written < maxFuncs) {
                if (monitor.isCancelled()) {
                    break;
                }
                Function func = it.next();
                if (func.isThunk() || func.isExternal()) {
                    continue;
                }
                DecompileResults res;
                try {
                    res = decomp.decompileFunction(func, 45, monitor);
                } catch (Exception e) {
                    continue;
                }
                if (res != null && res.decompileCompleted()) {
                    DecompiledFunction df = res.getDecompiledFunction();
                    if (df != null) {
                        f.write("// --- " + func.getName() + " @ "
                                + func.getEntryPoint() + " ---\n");
                        f.write(df.getC());
                        f.write("\n\n");
                        written++;
                    }
                }
            }
        } finally {
            f.close();
            decomp.dispose();
        }
        println("ReverseAI: decompiled " + written + " functions -> " + outPath);
    }
}
