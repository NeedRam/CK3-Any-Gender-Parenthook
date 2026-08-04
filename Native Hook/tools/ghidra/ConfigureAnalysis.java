// Keep headless analysis focused on code discovery and references. CK3's
// stripped executable makes the decompiler's global parameter-ID pass very
// expensive, and it is not needed to locate this validation branch.
import ghidra.app.script.GhidraScript;
import ghidra.framework.options.Options;
import ghidra.program.model.listing.Program;

public class ConfigureAnalysis extends GhidraScript {
    @Override
    protected void run() throws Exception {
        Options options = currentProgram.getOptions(Program.ANALYSIS_PROPERTIES);
        String[] disabled = {
            "Decompiler Parameter ID",
            "Decompiler Switch Analysis",
            "Windows x86 PE RTTI Analyzer",
            "Function ID"
        };
        for (String name : disabled) {
            options.setBoolean(name, false);
            println("DISABLED=" + name);
        }
    }
}
