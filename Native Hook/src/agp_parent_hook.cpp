#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "agp_build_profile.h"
#include "agp_close_family.h"
#include "agp_female_father.h"
#include "agp_history.h"
#include "agp_male_mother.h"
#include "agp_parent_roles.h"
#include "agp_patch_runtime.h"

namespace agp {
namespace {
DWORD WINAPI PatchThread(LPVOID) {
    try {
        if (!SelectAndValidateProfile()) return 1;
        BeginPatchTransaction();
        // Every game-code write is staged. Relay allocations and all modules
        // must succeed before any of the executable's instructions are changed.
        if (!StageCloseFamilyPatch() || !StageHistoryPatches() ||
            !StageFemaleFatherPatches() || !StageMaleMotherPatches() ||
            !StageParentRoleReconstruction() || !StageParentSerialization()) {
            AbortPatchTransaction();
            Log("AGP: staging failed; no game-code changes made.");
            return 1;
        }
        if (!CommitPatchTransaction()) return 1;
        Log("AGP v1.1.0: native patches committed. Gameplay acceptance is separate from patch preflight.");
        return 0;
    } catch (...) {
        AbortPatchTransaction();
        Log("AGP: preparation exception; no game-code changes made.");
        return 1;
    }
}
}
}
BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        HANDLE thread = CreateThread(nullptr, 0, agp::PatchThread, nullptr, 0, nullptr);
        if (thread) CloseHandle(thread);
    }
    return TRUE;
}
