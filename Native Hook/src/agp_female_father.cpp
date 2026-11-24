#include "agp_female_father.h"
#include "agp_build_profile.h"
#include "agp_parent_roles.h"
namespace agp {
bool StageFemaleFatherPatches() {
    return StageModulePatches("female") && StageParentPersistence(true);
}
}
