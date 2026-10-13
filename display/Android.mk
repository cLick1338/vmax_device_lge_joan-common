#Vmax
LOCAL_PATH := $(call my-dir)

# QDCM calibration with an identity HDR PCC, installed under the per-variant
# names libsdm-color looks up (DT panel name suffix)
JOAN_QDCM_SRC := vendor/lge/joan-common/proprietary/vendor/etc/qdcm_calib_data_SW43402_cmd_mode_dsc_dsi_panel.xml
JOAN_QDCM_GEN := $(call intermediates-dir-for,ETC,joan_qdcm_calib_idpcc)/qdcm_calib_idpcc.xml

$(JOAN_QDCM_GEN): $(LOCAL_PATH)/qdcm_identity_pcc.py $(JOAN_QDCM_SRC)
	@mkdir -p $(dir $@)
	$(hide) python3 $< $(JOAN_QDCM_SRC) $@

define joan-qdcm-calib-module
include $$(CLEAR_VARS)
LOCAL_MODULE := qdcm_calib_data_SW43402_cmd_mode_dsc_dsi_panel_$(1).xml
LOCAL_LICENSE_KINDS := legacy_proprietary
LOCAL_LICENSE_CONDITIONS := proprietary by_exception_only
LOCAL_MODULE_CLASS := ETC
LOCAL_VENDOR_MODULE := true
LOCAL_PREBUILT_MODULE_FILE := $$(JOAN_QDCM_GEN)
include $$(BUILD_PREBUILT)
endef

$(foreach v,2_0 2_1 3_0 3_1 4_0,$(eval $(call joan-qdcm-calib-module,$(v))))
