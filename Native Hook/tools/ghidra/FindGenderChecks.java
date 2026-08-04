// Reports likely character-gender checks in CK3's native executable.
// This is a candidate finder only; every result requires manual review.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.MemoryBlock;

import java.util.Locale;

public class FindGenderChecks extends GhidraScript {
    private static final String DEFAULT_GENDER_OFFSET = "199";

    private static String normalizeOffset(String value) {
        String normalized = value.toLowerCase(Locale.ROOT).trim();
        if (normalized.startsWith("0x")) {
            normalized = normalized.substring(2);
        }
        if (normalized.endsWith("h")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        return normalized;
    }

    private static boolean mentionsOffset(String instruction, String offset) {
        String normalized = instruction.toLowerCase(Locale.ROOT).replace(" ", "");
        return normalized.contains("0x" + offset) ||
            normalized.contains(offset + "h") ||
            normalized.contains("+" + offset);
    }

    private void printContext(Instruction instruction) {
        Instruction current = instruction;
        for (int index = 0; index < 3 && current != null; index++) {
            println("  ASM=" + current.getAddress() + " " + current);
            current = current.getNext();
        }
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        String genderOffset = normalizeOffset(args.length == 0 ? DEFAULT_GENDER_OFFSET : args[0]);
        MemoryBlock textBlock = currentProgram.getMemory().getBlock(".text");
        if (textBlock == null) {
            printerr("No .text memory block found.");
            return;
        }

        Listing listing = currentProgram.getListing();
        InstructionIterator instructions = listing.getInstructions(textBlock.getAddressSet(), true);
        int matches = 0;
        while (instructions.hasNext()) {
            Instruction instruction = instructions.next();
            if (!instruction.getMnemonicString().equalsIgnoreCase("CMP") ||
                !mentionsOffset(instruction.toString(), genderOffset)) {
                continue;
            }

            matches++;
            Address address = instruction.getAddress();
            Function function = getFunctionContaining(address);
            println("CANDIDATE=" + address +
                " FUNCTION=" + (function == null ? "<none>" : function.getEntryPoint() + " " + function.getName()));
            println("  CMP=" + instruction);
            printContext(instruction);
        }
        println("MATCHES=" + matches + " GENDER_FIELD_OFFSET=0x" + genderOffset);
    }
}
