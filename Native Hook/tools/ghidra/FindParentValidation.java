// Ghidra headless analysis helper for CK3 1.19.0.
// Locates the parent-sex validation text and prints code references and
// containing functions. It changes neither the executable nor the project.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.ReferenceIterator;

import java.nio.charset.StandardCharsets;

public class FindParentValidation extends GhidraScript {
    private static final String ERROR = "New parent must be of correct biological sex";

    @Override
    protected void run() throws Exception {
        StringBuilder bytes = new StringBuilder();
        for (byte value : ERROR.getBytes(StandardCharsets.US_ASCII)) {
            if (bytes.length() > 0) {
                bytes.append(' ');
            }
            bytes.append(String.format("%02x", value & 0xff));
        }

        Address[] matches = findBytes(currentProgram.getMinAddress(), bytes.toString(), 10, 1);
        println("MATCHES=" + matches.length);
        ReferenceManager references = currentProgram.getReferenceManager();
        for (Address address : matches) {
            println("STRING=" + address);
            ReferenceIterator refs = references.getReferencesTo(address);
            int referenceCount = 0;
            while (refs.hasNext()) {
                Reference ref = refs.next();
                referenceCount++;
                Address from = ref.getFromAddress();
                Function function = getFunctionContaining(from);
                println("XREF=" + from + " FUNCTION=" +
                    (function == null ? "<none>" : function.getEntryPoint() + " " + function.getName()));
            }
            println("XREF_COUNT=" + referenceCount);
        }
    }
}
