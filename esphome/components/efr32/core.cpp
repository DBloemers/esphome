#ifdef USE_EFR32

#include "esphome/core/helpers.h"

#include <algorithm>
#include <zephyr/drivers/hwinfo.h>

namespace esphome::efr32 {}  // namespace esphome::efr32

namespace esphome {

void get_mac_address_raw(uint8_t *mac) {
  // The Zephyr driver returns the Silicon Labs 64-bit unique ID in big-endian order.
  // Derive a locally administered unicast address from its low 48 bits.
  uint8_t id[8]{};
  hwinfo_get_device_id(id, sizeof(id));
  std::copy_n(id + 2, 6, mac);
  mac[0] = (mac[0] & 0xFC) | 0x02;
}

}  // namespace esphome

#endif
