#include "agp_male_mother.h"
#include "agp_build_profile.h"
#include "agp_parent_roles.h"
namespace agp {
bool StageMaleMotherPatches() {
    return StageModulePatches("male") && StageParentPersistence(false);
}
}
