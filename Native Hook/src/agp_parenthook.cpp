#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "agp_female_father.h"
#include "agp_history.h"
#include "agp_male_mother.h"
#include "agp_parent_roles.h"
#include "agp_patch_runtime.h"

namespace agp {
namespace {

bool ApplyPatch() {
	TextSection text{};
	if (!GetTextSection(&text)) {
		Log("AGP Parenthook: unable to locate ck3.exe .text section; no changes made.");
		return false;
	}

	FemaleFatherPatchPlan female_father{};
	MaleMotherPatchPlan male_mother{};
	HistoryPatchPlan history{};
	ParentRoleReconstructionPlan reconstruction{};
	const bool female_ok = PrepareFemaleFatherPatch(text, &female_father);
	const bool male_ok = PrepareMaleMotherPatch(text, &male_mother);
	const bool history_ok = PrepareHistoryPatch(text, &history);
	const bool reconstruction_ok = PrepareParentRoleReconstruction(text, &reconstruction);
	if (!female_ok || !male_ok || !history_ok || !reconstruction_ok) {
		return false;
	}

	const bool history_applied = ApplyHistoryPatch(history);
	const bool female_applied = ApplyFemaleFatherPatch(female_father);
	const bool male_applied = ApplyMaleMotherPatch(male_mother);
	const bool reconstruction_applied = ApplyParentRoleReconstruction(reconstruction);
	if (!history_applied || !female_applied || !male_applied || !reconstruction_applied) {
		Log("AGP Parenthook: patch write failed; CK3 may be unchanged or partially patched. Exit without saving and report the log.");
		return false;
	}
	Log("AGP Parenthook: enabled female fathers and male mothers for runtime setters, male-carrier pregnancy, history, and persisted native parent roles.");
	return true;
}

DWORD WINAPI PatchThread(LPVOID) {
	ApplyPatch();
	return 0;
}

} // namespace
} // namespace agp

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
	if (reason == DLL_PROCESS_ATTACH) {
		DisableThreadLibraryCalls(module);
		HANDLE thread = CreateThread(nullptr, 0, agp::PatchThread, nullptr, 0, nullptr);
		if (thread != nullptr) {
			CloseHandle(thread);
		}
	}
	return TRUE;
}
