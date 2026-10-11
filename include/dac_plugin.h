/*
 * Copyright (C) 2024 The LineageOS Project
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

/*
 * Board specific devices and paths
 *
 * If your device exposes these controls in another place, you can either
 * symlink to the locations given here, or override this header in your
 * device tree.
 */

#define DEFAULT_BACKEND "headphones"
#define DEFAULT_INTERFACE "SLIMBUS_6_RX"
#define ESS_BYPASS_MODE_MIXER_PATH "ess-bypass-mode"

// The HAL gives the "hifi-dac" backend its own rate rules and drives the interface's format controls
#define HIFI_DAC_BACKEND "hifi-dac"
#define HIFI_DAC_INTERFACE "QUAT_MI2S_RX"
#define ESS_HIFI_MODE_MIXER_PATH "ess-hifi-mode"
