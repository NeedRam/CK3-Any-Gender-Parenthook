// Prints a bounded disassembly window for a candidate function address.
// Usage: InspectFunction.java <address> [instruction_limit]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.listing.Listing;

public class InspectFunction extends GhidraScript {
    private static final int DEFAULT_LIMIT = 160;

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length == 0) {
            printerr("Usage: InspectFunction.java <address> [instruction_limit]");
            return;
        }

        Address address = toAddr(args[0]);
        Function function = getFunctionContaining(address);
        if (function == null) {
            function = getFunctionAt(address);
        }
        if (function == null) {
            printerr("No function contains or starts at " + address + ".");
            return;
        }

        int limit = DEFAULT_LIMIT;
        if (args.length > 1) {
            limit = Integer.parseInt(args[1]);
        }

        println("FUNCTION=" + function.getEntryPoint() + " " + function.getName());
        println("BODY=" + function.getBody());
        Listing listing = currentProgram.getListing();
        InstructionIterator instructions = listing.getInstructions(function.getBody(), true);
        int count = 0;
        while (instructions.hasNext() && count < limit) {
            Instruction instruction = instructions.next();
            println("ASM=" + instruction.getAddress() + " " + instruction);
            count++;
        }
        println("INSTRUCTIONS_PRINTED=" + count);
    }
}
