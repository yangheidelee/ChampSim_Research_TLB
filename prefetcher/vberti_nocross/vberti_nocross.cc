#define NO_CROSS_PAGE
#define vberti vberti_nocross
#define vberti_space vberti_nocross_space
#include "../vberti/vberti.h"
#include "vberti_nocross_impl.inc"
#undef vberti_space
#undef vberti
#undef NO_CROSS_PAGE
