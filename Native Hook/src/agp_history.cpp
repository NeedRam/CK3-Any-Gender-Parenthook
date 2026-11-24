#include "agp_history.h"
#include "agp_build_profile.h"
namespace agp {
bool StageHistoryPatches() { return StageModulePatches("history"); }
}
