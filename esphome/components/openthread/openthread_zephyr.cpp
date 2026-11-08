#include "esphome/core/defines.h"
#if defined(USE_OPENTHREAD) && defined(USE_ZEPHYR)
#include <openthread/dataset.h>
#include <openthread/thread.h>
#include <openthread/logging.h>
#include "openthread.h"
#include "esphome/core/helpers.h"
#include <zephyr/net/net_ip.h>
#ifdef USE_EFR32
#include <openthread.h>
#else
#include <zephyr/net/openthread.h>
#endif

ESPHOME_LOG_TAG(TAG, "openthread");

namespace esphome::openthread {

static void on_thread_state_changed(otChangedFlags flags, otInstance *instance) {
  // Delegate connection status tracking to common callback
  if (global_openthread_component != nullptr) {
    OpenThreadComponent::on_state_changed(flags, global_openthread_component);
  }
  if (flags & OT_CHANGED_THREAD_ROLE) {
    otDeviceRole role = otThreadGetDeviceRole(instance);
    ESP_LOGI(TAG, "Thread role changed to %s", otThreadDeviceRoleToString(role));
  }
  if (flags & OT_CHANGED_THREAD_NETDATA) {
    ESP_LOGI(TAG, "Thread network data updated");
  }
  if (flags & (OT_CHANGED_THREAD_ROLE | OT_CHANGED_THREAD_NETDATA)) {
    char buf[NET_IPV6_ADDR_LEN];
    for (const otNetifAddress *addr = otIp6GetUnicastAddresses(instance); addr != nullptr; addr = addr->mNext) {
      ESP_LOGI(TAG, "  Address: %s", net_addr_ntop(AF_INET6, &addr->mAddress, buf, sizeof(buf)));
    }
  }
}

// EFR32 uses upstream Zephyr's OpenThread module; the Nordic SDK still
// exposes the older L2 context API.
#ifdef USE_EFR32
static struct openthread_state_changed_callback ot_state_changed_cb = {
    .otCallback = [](otChangedFlags flags,
                     void *) { on_thread_state_changed(flags, openthread_get_default_instance()); },
};

static int start_openthread() {
  int err = openthread_state_changed_callback_register(&ot_state_changed_cb);
  if (err != 0) {
    return err;
  }
  err = openthread_run();
  if (err != 0) {
    openthread_state_changed_callback_unregister(&ot_state_changed_cb);
  }
  return err;
}
#else
static struct openthread_state_changed_cb ot_state_changed_cb = {
    .state_changed_cb = [](otChangedFlags flags, struct openthread_context *context,
                           void *) { on_thread_state_changed(flags, context->instance); },
};

static int start_openthread() {
  auto *context = openthread_get_default_context();
  openthread_state_changed_cb_register(context, &ot_state_changed_cb);
  openthread_start(context);
  return 0;
}
#endif

static bool configure_dataset(otInstance *instance) {
  otOperationalDatasetTlvs dataset = {};

#ifndef USE_OPENTHREAD_FORCE_DATASET
  otError error = otDatasetGetActiveTlvs(instance, &dataset);
  if (error != OT_ERROR_NONE) {
    dataset.mLength = 0;
  } else {
    ESP_LOGI(TAG, "Found existing dataset, ignoring config (force_dataset: true to override)");
  }
#endif

#ifdef USE_OPENTHREAD_TLVS
  if (dataset.mLength == 0) {
    const size_t tlv_chars = sizeof(USE_OPENTHREAD_TLVS) - 1;
    if ((tlv_chars % 2) != 0) {
      ESP_LOGE(TAG, "Invalid OpenThread TLV hex string length (must be even, got %zu)", tlv_chars);
      return false;
    }

    size_t len = tlv_chars / 2;
    if (len > sizeof(dataset.mTlvs)) {
      ESP_LOGE(TAG, "OpenThread TLV too long (max %zu bytes, got %zu bytes)", sizeof(dataset.mTlvs), len);
      return false;
    }

    size_t parsed = parse_hex(USE_OPENTHREAD_TLVS, tlv_chars, dataset.mTlvs, len);
    if (parsed != tlv_chars) {
      ESP_LOGE(TAG, "Invalid OpenThread TLV hex string (expected %zu hex chars, got %zu)", tlv_chars, parsed);
      return false;
    }
    dataset.mLength = len;
  }
#endif
  if (dataset.mLength > 0) {
    otError error = otDatasetSetActiveTlvs(instance, &dataset);
    if (error != OT_ERROR_NONE) {
      ESP_LOGE(TAG, "Failed to set active dataset: %s", otThreadErrorToString(error));
      return false;
    }
  }
  return true;
}

void OpenThreadComponent::setup() {
  auto *instance = this->get_openthread_instance_();
  if (instance == nullptr) {
    ESP_LOGE(TAG, "OpenThread instance is unavailable");
    this->teardown_stage_ = TeardownStage::TEARDOWN_STAGE_COMPLETED;
    this->mark_failed();
    return;
  }

  {
    auto lock = InstanceLock::acquire();
    if (!configure_dataset(instance)) {
      this->teardown_stage_ = TeardownStage::TEARDOWN_STAGE_COMPLETED;
      this->mark_failed();
      return;
    }
  }
  if (const int err = start_openthread(); err != 0) {
    ESP_LOGE(TAG, "Failed to start OpenThread: %d", err);
    this->teardown_stage_ = TeardownStage::TEARDOWN_STAGE_COMPLETED;
    this->mark_failed();
    return;
  }
  this->lock_initialized_ = true;

  InstanceLock lock = InstanceLock::acquire();
  this->apply_linkmode_(lock.get_instance());
}

otInstance *OpenThreadComponent::get_openthread_instance_() { return openthread_get_default_instance(); }

int OpenThreadComponent::openthread_stop_() {
  // The shared teardown already disables Thread and IPv6 synchronously.
  this->teardown_stage_ = TeardownStage::TEARDOWN_STAGE_COMPLETED;
  return 0;
}

network::IPAddresses OpenThreadComponent::get_ip_addresses() {
  network::IPAddresses addresses;
  auto lock = InstanceLock::acquire();
  size_t addr_count = 0;
  for (const otNetifAddress *addr = otIp6GetUnicastAddresses(lock.get_instance());
       addr != nullptr && addr_count + 1 < addresses.size(); addr = addr->mNext) {
    struct in6_addr ip6;
    memcpy(&ip6, addr->mAddress.mFields.m8, sizeof(ip6));
    addresses[addr_count + 1] = network::IPAddress(&ip6);
    addr_count++;
  }
  return addresses;
}

InstanceLock InstanceLock::try_acquire(int delay) {
  if (global_openthread_component == nullptr || !global_openthread_component->is_lock_initialized()) {
    return InstanceLock(false);
  }
#ifdef USE_EFR32
  // The upstream module exposes only a nonblocking or an indefinite lock.
  const auto deadline = sys_timepoint_calc(K_MSEC(delay));
  do {
    if (openthread_mutex_try_lock() == 0) {
      return InstanceLock(true);
    }
    if (sys_timepoint_expired(deadline)) {
      break;
    }
    k_sleep(K_TICKS(1));
  } while (!sys_timepoint_expired(deadline));
#else
  struct openthread_context *ot_context = openthread_get_default_context();
  if (k_mutex_lock(&ot_context->api_lock, K_MSEC(delay)) == 0) {
    return InstanceLock(true);
  }
#endif
  return InstanceLock(false);
}

InstanceLock InstanceLock::acquire() {
#ifdef USE_EFR32
  openthread_mutex_lock();
#else
  struct openthread_context *ot_context = openthread_get_default_context();
  k_mutex_lock(&ot_context->api_lock, K_FOREVER);
#endif
  return InstanceLock(true);
}

otInstance *InstanceLock::get_instance() { return openthread_get_default_instance(); }

InstanceLock::~InstanceLock() {
  if (this->owns_) {
#ifdef USE_EFR32
    openthread_mutex_unlock();
#else
    struct openthread_context *ot_context = openthread_get_default_context();
    k_mutex_unlock(&ot_context->api_lock);
#endif
  }
}

}  // namespace esphome::openthread
#endif
