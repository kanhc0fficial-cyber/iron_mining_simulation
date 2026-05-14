# V4 Migration Audit Report

Source: `DESIGN_V4_FACTORY_CAUSAL_SIMULATION.md`
Formula assignments extracted: **581**
Unique assigned LHS variables: **512**
LHS assigned more than once: **68**
LHS assigned in multiple sections/subsections: **68**
DCS variables listed in tables/inline refs: **67**
DCS variables with explicit `=meas(...)`: **59**
Listed DCS without explicit meas line: **13**
Explicit meas not listed in DCS tables: **5**

## Cross-Section Duplicate Assignments

### `C_feed`
- line 588: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `C_feed=C_feed_prev+(dt/max(tau_cyc_pool,eps))*(C_feed_in-C_feed_prev)`
- line 1301: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `C_feed = C_feed_prev+(dt/max(tau_cyc_pool,eps))*(C_feed_in-C_feed_prev)`

### `C_feed_in`
- line 582: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `C_feed_in=(M_mag_conc_solid+M_tm_discharge_solid_prev)/max(M_mag_conc_wet+M_tm_discharge_wet_prev+M_water_add,eps)`
- line 1291: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `C_feed_in = (M_mag_conc_solid+M_tm_discharge_solid_prev)/max(M_mag_conc_wet+M_tm_discharge_wet_prev+M_water_add,eps)`

### `C_mill`
- line 638: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `C_mill=M_sand/max(M_sand+M_mill_water_in,eps)`
- line 1359: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `C_mill = M_sand/max(M_sand+M_mill_water_in,eps)`

### `DCS`
- line 82: 1. 对旧设计的重新判定 / 1.2 新设计的核心原则 -> `DCS = a*y + noise`
- line 83: 1. 对旧设计的重新判定 / 1.2 新设计的核心原则 -> `DCS = a*final_conc_tfe + noise`
- line 263: 2. 全局变量分类 / 2.3 DCS、lab、标签 -> `DCS = 在线传感器或控制系统可见值，可作 DCS-only 特征。`

### `E_spec`
- line 652: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `E_spec=P_mech/max(M_sand,eps)`
- line 1373: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `E_spec = P_mech/max(M_sand,eps)`

### `F325_discharge`
- line 669: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `F325_discharge=F325_discharge_prev+(dt/max(tau_mill_residence,eps))*(F325_discharge_inst-F325_discharge_prev)`
- line 1379: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `F325_discharge = F325_discharge_prev+(dt/max(tau_mill_residence,eps))*(F325_discharge_inst-F325_discharge_prev)`

### `F325_discharge_inst`
- line 653: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `F325_discharge_inst=clip(F325_sand+kE*log1p(E_spec/max(WI_mill,eps))-k_over*f25,0,1)`
- line 1374: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `F325_discharge_inst = clip(F325_sand+kE*log1p(E_spec/max(WI_mill,eps))-k_over*f25,0,1)`

### `F325_feed`
- line 589: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `F325_feed=F325_feed_prev+(dt/max(tau_cyc_pool,eps))*(F325_feed_in-F325_feed_prev)`
- line 1302: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `F325_feed = F325_feed_prev+(dt/max(tau_cyc_pool,eps))*(F325_feed_in-F325_feed_prev)`

### `F325_feed_in`
- line 583: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `F325_feed_in=(M_mag_conc_solid*F325_mag_conc+M_tm_discharge_solid_prev*F325_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)`
- line 1292: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `F325_feed_in = (M_mag_conc_solid*F325_mag_conc+M_tm_discharge_solid_prev*F325_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)`

### `F325_mixed`
- line 218: 2. 全局变量分类 / 2.2 隐藏物料状态 -> `F325_mixed = (M_solid_in1*F325_in1+M_solid_in2*F325_in2) / max(M_solid_in1+M_solid_in2,eps)`
- line 407: 4. 入口边界因果模型 /  -> `F325_mixed = sum_i(M_solid_i*F325_i)/max(M_solid_mixed,eps)`

### `F325_overflow`
- line 613: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `F325_overflow = clip(F325_feed*k_fine_enrich/max(alpha_ov,eps),F325_feed,1.0)`
- line 1345: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `F325_overflow = clip(F325_feed*k_fine_enrich/max(alpha_ov,eps),F325_feed,1.0)`

### `F325_sand`
- line 617: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `F325_sand = clip( (F325_feed-F325_overflow*alpha_ov)/max(1-alpha_ov,eps), 0,F325_feed)`
- line 1348: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `F325_sand = clip((F325_feed-F325_overflow*alpha_ov)/max(1-alpha_ov,eps),0,F325_feed)`

### `I_exc`
- line 476: 5. 磁选因果模型 / 5.2 控制设定不得孤立 -> `I_exc=sat_act(I_exc_sp,I_min,I_max,tau_exc)`
- line 1215: 10. DCS 具体生成公式和代理防护 / 10.2 磁选 DCS 具体公式 -> `I_exc = I_exc_sp+(I_exc_prev-I_exc_sp)*exp(-dt/tau_exc_act)`

### `I_exc_sp`
- line 469: 5. 磁选因果模型 / 5.2 控制设定不得孤立 -> `I_exc_sp = clip(I_nom + Kdiff_I*magnetic_difficulty - Kmag_I*(r_mag-r_mag_ref) + operator_trim_I + PRBS_mag_I, I_min,I_max)`
- line 1214: 10. DCS 具体生成公式和代理防护 / 10.2 磁选 DCS 具体公式 -> `I_exc_sp = clip(I_nom+Kdiff_I*magnetic_difficulty-Kmag_I*(r_mag-r_mag_ref)+operator_trim_I+PRBS_mag_I,I_min,I_max)`

### `Liberation_fe_discharge`
- line 670: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `Liberation_fe_discharge=Liberation_fe_discharge_prev+(dt/max(tau_mill_residence,eps))*(Liberation_fe_discharge_inst-Liberation_fe_discharge_prev)`
- line 1380: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_fe_discharge = Liberation_fe_discharge_prev+(dt/max(tau_mill_residence,eps))*(Liberation_fe_discharge_inst-Liberation_fe_discharge_prev)`

### `Liberation_fe_discharge_inst`
- line 654: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `Liberation_fe_discharge_inst = clip( Liberation_fe_sand + k_lib_fe*(E_spec/max(WI_mill,eps))*liberation_potential*(1-Liberation_fe_sand), 0,1)`
- line 1375: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_fe_discharge_inst = clip(Liberation_fe_sand+k_lib_fe*(E_spec/max(WI_mill,eps))*liberation_potential*(1-Liberation_fe_sand),0,1)`

### `Liberation_fe_feed`
- line 590: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `Liberation_fe_feed=Liberation_fe_feed_prev+(dt/max(tau_cyc_pool,eps))*(Liberation_fe_feed_in-Liberation_fe_feed_prev)`
- line 1303: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_fe_feed = Liberation_fe_feed_prev+(dt/max(tau_cyc_pool,eps))*(Liberation_fe_feed_in-Liberation_fe_feed_prev)`

### `Liberation_fe_feed_in`
- line 584: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `Liberation_fe_feed_in=(M_mag_conc_solid*Liberation_fe_mag_conc+M_tm_discharge_solid_prev*Liberation_fe_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)`
- line 1293: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_fe_feed_in = (M_mag_conc_solid*Liberation_fe_mag_conc+M_tm_discharge_solid_prev*Liberation_fe_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)`

### `Liberation_fe_mixed`
- line 222: 2. 全局变量分类 / 2.2 隐藏物料状态 -> `Liberation_fe_mixed = (M_solid_in1*Liberation_fe_in1+M_solid_in2*Liberation_fe_in2) / max(M_solid_in1+M_solid_in2,eps)`
- line 409: 4. 入口边界因果模型 /  -> `Liberation_fe_mixed = sum_i(M_solid_i*Liberation_fe_i)/max(M_solid_mixed,eps)`

### `Liberation_fe_overflow`
- line 614: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `Liberation_fe_overflow = clip(Liberation_fe_feed*k_lib_fe_enrich,Liberation_fe_feed,1.0)`
- line 1346: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_fe_overflow = clip(Liberation_fe_feed*k_lib_fe_enrich,Liberation_fe_feed,1.0)`

### `Liberation_fe_sand`
- line 620: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `Liberation_fe_sand = clip( (Liberation_fe_feed-Liberation_fe_overflow*alpha_ov)/max(1-alpha_ov,eps), 0,Liberation_fe_feed)`
- line 1349: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_fe_sand = clip((Liberation_fe_feed-Liberation_fe_overflow*alpha_ov)/max(1-alpha_ov,eps),0,Liberation_fe_feed)`

### `Liberation_gangue_discharge`
- line 671: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `Liberation_gangue_discharge=Liberation_gangue_discharge_prev+(dt/max(tau_mill_residence,eps))*(Liberation_gangue_discharge_inst-Liberation_gangue_discharge_prev)`
- line 1381: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_gangue_discharge = Liberation_gangue_discharge_prev+(dt/max(tau_mill_residence,eps))*(Liberation_gangue_discharge_inst-Liberation_gangue_discharge_prev)`

### `Liberation_gangue_discharge_inst`
- line 658: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `Liberation_gangue_discharge_inst = clip( Liberation_gangue_sand + k_lib_g*(E_spec/max(WI_mill,eps))*liberation_potential*(1-Liberation_gangue_sand), 0,1)`
- line 1376: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_gangue_discharge_inst = clip(Liberation_gangue_sand+k_lib_g*(E_spec/max(WI_mill,eps))*liberation_potential*(1-Liberation_gangue_sand),0,1)`

### `Liberation_gangue_feed`
- line 591: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `Liberation_gangue_feed=Liberation_gangue_feed_prev+(dt/max(tau_cyc_pool,eps))*(Liberation_gangue_feed_in-Liberation_gangue_feed_prev)`
- line 1304: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_gangue_feed = Liberation_gangue_feed_prev+(dt/max(tau_cyc_pool,eps))*(Liberation_gangue_feed_in-Liberation_gangue_feed_prev)`

### `Liberation_gangue_feed_in`
- line 585: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `Liberation_gangue_feed_in=(M_mag_conc_solid*Liberation_gangue_mag_conc+M_tm_discharge_solid_prev*Liberation_gangue_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)`
- line 1294: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_gangue_feed_in = (M_mag_conc_solid*Liberation_gangue_mag_conc+M_tm_discharge_solid_prev*Liberation_gangue_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)`

### `Liberation_gangue_mixed`
- line 226: 2. 全局变量分类 / 2.2 隐藏物料状态 -> `Liberation_gangue_mixed = (M_solid_in1*Liberation_gangue_in1+M_solid_in2*Liberation_gangue_in2) / max(M_solid_in1+M_solid_in2,eps)`
- line 410: 4. 入口边界因果模型 /  -> `Liberation_gangue_mixed = sum_i(M_solid_i*Liberation_gangue_i)/max(M_solid_mixed,eps)`

### `Liberation_gangue_overflow`
- line 615: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `Liberation_gangue_overflow = clip(Liberation_gangue_feed*k_lib_g_enrich,Liberation_gangue_feed,1.0)`
- line 1347: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_gangue_overflow = clip(Liberation_gangue_feed*k_lib_g_enrich,Liberation_gangue_feed,1.0)`

### `Liberation_gangue_sand`
- line 623: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `Liberation_gangue_sand = clip( (Liberation_gangue_feed-Liberation_gangue_overflow*alpha_ov)/max(1-alpha_ov,eps), 0,Liberation_gangue_feed)`
- line 1350: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Liberation_gangue_sand = clip((Liberation_gangue_feed-Liberation_gangue_overflow*alpha_ov)/max(1-alpha_ov,eps),0,Liberation_gangue_feed)`

### `M_mill_water_in`
- line 637: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `M_mill_water_in=M_sand_water+Q_sand_water_phys*rho_water`
- line 1358: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `M_mill_water_in = M_tm_sand_water+Q_sand_water_phys*rho_water`

### `P_cyc`
- line 574: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `P_cyc=clip(kP*rho_slurry*(Q_pump/max(N_cyc_on,1))^2,P_min,P_max)`
- line 1316: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `P_cyc = clip(kP*rho_feed*(Q_pump/max(N_cyc_on,1))^2,P_min,P_max)`

### `P_cyc_lag`
- line 570: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `P_cyc_lag=delay(P_cyc,L_pump_pressure)`
- line 1312: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `P_cyc_lag = delay(P_cyc,L_pump_pressure)`

### `P_mech`
- line 649: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `P_mech=ZOH(P_mech,clip(P_mech_ss,0,1.15*P_rated),tau_P)`
- line 1370: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `P_mech = P_mech_ss+(P_mech_prev-P_mech_ss)*exp(-dt/tau_P)`

### `P_mech_ss`
- line 648: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `P_mech_ss=P_idle+P_media+kM*M_sand*(1+grind_difficulty)`
- line 1369: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `P_mech_ss = P_idle+P_media+kM*M_sand*(1+grind_difficulty)`

### `Q_overflow`
- line 610: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `Q_overflow = M_overflow_solid/rho_solid_mix + M_overflow_water/rho_water`
- line 1339: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Q_overflow = M_tm_overflow_solid/rho_solid_mix + M_tm_overflow_water/rho_water`

### `Q_pump`
- line 573: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `Q_pump=k_pump*f_pump*(1-exp(-max(L_pool,0)/max(L_min_safe,eps)))*health_pump`
- line 1315: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `Q_pump = k_pump*f_pump*(1-exp(-max(L_pool,0)/max(L_min_safe,eps)))*health_pump`

### `T_slurry_discharge`
- line 672: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `T_slurry_discharge=T_slurry_discharge_prev+(dt/max(tau_mill_residence,eps))*(T_slurry_discharge_inst-T_slurry_discharge_prev)`
- line 1382: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `T_slurry_discharge = T_slurry_discharge_prev+(dt/max(tau_mill_residence,eps))*(T_slurry_discharge_inst-T_slurry_discharge_prev)`

### `T_slurry_discharge_inst`
- line 664: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `T_slurry_discharge_inst = T_slurry_sand + delta_T_mill - k_cool_pipe*max(T_slurry_sand-T_amb,0)`
- line 1378: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `T_slurry_discharge_inst = T_slurry_sand+delta_T_mill-k_cool_pipe*max(T_slurry_sand-T_amb,0)`

### `T_slurry_mixed`
- line 230: 2. 全局变量分类 / 2.2 隐藏物料状态 -> `T_slurry_mixed = (M_wet_in1*Cp_slurry_in1*T_slurry_in1+M_wet_in2*Cp_slurry_in2*T_slurry_in2) / max(M_wet_in1*Cp_slurry_in1+M_wet_in2*Cp_slurry_in2,eps)`
- line 411: 4. 入口边界因果模型 /  -> `T_slurry_mixed = sum_i(M_wet_i*Cp_slurry_i*T_slurry_i)/max(sum_i(M_wet_i*Cp_slurry_i),eps)`

### `T_slurry_overflow`
- line 627: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `T_slurry_overflow = T_slurry_feed-k_cool_cyc*max(T_slurry_feed-T_amb,0)`
- line 1351: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `T_slurry_overflow = T_slurry_feed-k_cool_cyc*max(T_slurry_feed-T_amb,0)`

### `T_slurry_sand`
- line 628: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `T_slurry_sand = T_slurry_feed-k_cool_sand*max(T_slurry_feed-T_amb,0)`
- line 1353: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `T_slurry_sand = T_slurry_feed-k_cool_sand*max(T_slurry_feed-T_amb,0)`

### `WI_discharge`
- line 673: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `WI_discharge=WI_mill`
- line 1383: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `WI_discharge = WI_mill`

### `WI_feed`
- line 592: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `WI_feed=WI_feed_prev+(dt/max(tau_cyc_pool,eps))*(WI_feed_in-WI_feed_prev)`
- line 1305: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `WI_feed = WI_feed_prev+(dt/max(tau_cyc_pool,eps))*(WI_feed_in-WI_feed_prev)`

### `WI_feed_in`
- line 586: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `WI_feed_in=(M_mag_conc_solid*WI_mag_conc+M_tm_discharge_solid_prev*WI_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)`
- line 1295: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `WI_feed_in = (M_mag_conc_solid*WI_mag_conc+M_tm_discharge_solid_prev*WI_discharge_prev)/max(M_mag_conc_solid+M_tm_discharge_solid_prev,eps)`

### `WI_mill`
- line 639: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `WI_mill=WI_sand`
- line 1360: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `WI_mill = WI_sand`

### `agg_tm_motor_current`
- line 1130: 10. DCS 具体生成公式和代理防护 /  -> `agg_tm_motor_current = meas(I_tm_phys)`
- line 1420: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `agg_tm_motor_current = meas(I_tm_phys)`

### `alpha_ov`
- line 599: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `alpha_ov=clip(sigmoid(kF*(F325_feed-F325_ref)+kP*(P_cyc-P_ref)-kC*(C-C_ref)-kmu*(mu_slurry-mu_ref)),0,1)`
- line 1329: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `alpha_ov = clip( sigmoid(kF*(F325_feed-F325_ref)+kP*(P_cyc-P_ref)-kC*(C_feed-C_ref)-kmu*(mu_feed-mu_ref)), 0,1)`

### `alpha_ov_water`
- line 606: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `alpha_ov_water = clip(alpha_ov*k_water_split,0,1)`
- line 1336: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `alpha_ov_water = clip(alpha_ov*k_water_split,0,1)`

### `circulating_load`
- line 635: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `circulating_load=clip(inst_circ_load,0.0,5.0)`
- line 1357: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `circulating_load = clip(inst_circ_load,0.0,5.0)`

### `circulating_load_lag`
- line 636: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `circulating_load_lag=delay(circulating_load,L_sand_control)`
- line 1323: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `circulating_load_lag = delay(circulating_load,L_sand_control)`

### `clog_buildup`
- line 496: 5. 磁选因果模型 / 5.2 控制设定不得孤立 -> `clog_buildup = c0 + c_clay*clay + c_f25*f25 + c_C*C + c_load*Q_feed/max(Q_ref,eps)`
- line 1224: 10. DCS 具体生成公式和代理防护 / 10.2 磁选 DCS 具体公式 -> `clog_buildup = c0 + c_clay*clay + c_f25*f25 + c_C*C + c_load*Q_feed/max(Q_ref,eps)`

### `clog_wash`
- line 502: 5. 磁选因果模型 / 5.2 控制设定不得孤立 -> `clog_wash = c_flush_Q*Q_flush_lag/max(Q_flush_ref,eps) + c_pul_clog*f_pul_lag/max(f_pul_ref,eps)`
- line 1230: 10. DCS 具体生成公式和代理防护 / 10.2 磁选 DCS 具体公式 -> `clog_wash = c_flush_Q*Q_flush_prev/max(Q_flush_ref,eps) + c_pul_clog*f_pul_prev/max(f_pul_ref,eps)`

### `d50`
- line 598: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `d50=d50_ref*(P_ref/max(P_cyc,eps))^aP*(C/C_ref)^aC*(mu_slurry/mu_ref)^amu`
- line 1328: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `d50 = d50_ref*(P_ref/max(P_cyc,eps))^aP*(C_feed/C_ref)^aC*(mu_feed/mu_ref)^amu`

### `dL_pool/dt`
- line 569: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `dL_pool/dt=(Q_in-Q_pump-Q_spill)/A_pool`
- line 1311: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `dL_pool/dt = (Q_in+Q_return_sand+Q_water-Q_pump)/A_pool`

### `delta_T_mill`
- line 663: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `delta_T_mill = P_mech*k_heat_conv/max(Q_pump*rho_slurry*Cp_slurry,eps)`
- line 1377: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `delta_T_mill = P_mech*k_heat_conv/max(Q_pump*rho_feed*Cp_slurry,eps)`

### `f_pul`
- line 490: 5. 磁选因果模型 / 5.2 控制设定不得孤立 -> `f_pul=sat_act(f_pul_sp,f_pul_min,f_pul_max,tau_pul)`
- line 1236: 10. DCS 具体生成公式和代理防护 / 10.2 磁选 DCS 具体公式 -> `f_pul = f_pul_sp+(f_pul_prev-f_pul_sp)*exp(-dt/tau_pul_act)`

### `f_pul_sp`
- line 483: 5. 磁选因果模型 / 5.2 控制设定不得孤立 -> `f_pul_sp=clip(f_pul_nom + Kcoarse_pul*(1-F325) + Kclay_pul*clay + Kslime_pul*f25 + Kload_pul*(Q_feed-Q_ref) + operator_trim_pul, f_pul_min,f_pul_max)`
- line 1234: 10. DCS 具体生成公式和代理防护 / 10.2 磁选 DCS 具体公式 -> `f_pul_sp = clip(f_pul_nom+Kcoarse_pul*(1-F325)+Kclay_pul*clay+Kslime_pul*f25+Kload_pul*(Q_feed-Q_ref)/max(Q_ref,eps),f_pul_min,f_pul_max)`

### `f_pump`
- line 572: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `f_pump=sat_act(f_pump_sp,f_min,f_max,tau_pump)`
- line 1314: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `f_pump = f_pump_sp+(f_pump_prev-f_pump_sp)*exp(-dt/tau_pump_act)`

### `f_pump_sp`
- line 571: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `f_pump_sp=clip(f0+Kp_L*(L_pool-L_sp)+Kp_P*(P_sp-P_cyc_lag)+Kff_Q*Q_in,f_min,f_max)`
- line 1313: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `f_pump_sp = clip(f0+K_L*(L_pool-L_sp)+K_P*(P_sp-P_cyc_lag)+K_Qff*Q_in,f_min,f_max)`

### `f_ring`
- line 512: 5. 磁选因果模型 / 5.2 控制设定不得孤立 -> `f_ring=sat_act(f_ring_sp,f_ring_min,f_ring_max,tau_ring)`
- line 1237: 10. DCS 具体生成公式和代理防护 / 10.2 磁选 DCS 具体公式 -> `f_ring = f_ring_sp+(f_ring_prev-f_ring_sp)*exp(-dt/tau_ring_act)`

### `f_ring_sp`
- line 507: 5. 磁选因果模型 / 5.2 控制设定不得孤立 -> `f_ring_sp=clip(f_ring_nom + Kclog_ring*matrix_clog + Kcoarse_ring*(1-F200) + operator_trim_ring, f_ring_min,f_ring_max)`
- line 1235: 10. DCS 具体生成公式和代理防护 / 10.2 磁选 DCS 具体公式 -> `f_ring_sp = clip(f_ring_nom+Kclog_ring*matrix_clog+Kcoarse_ring*(1-F200),f_ring_min,f_ring_max)`

### `floatability_difficulty`
- line 746: 7. 浮选因果模型 / 7.3 药剂控制 -> `floatability_difficulty = w_carb*r_carb + w_sil*r_sil + w_fine*f25 + w_coarse*(1-F325) + w_low_lib*(1-Liberation_gangue) + w_density*abs(C-C_opt) + w_clay*clay`
- line 1478: 10. DCS 具体生成公式和代理防护 / 10.4 浮选 DCS 具体公式 -> `floatability_difficulty = w_carb*r_carb + w_sil*r_sil + w_fine*f25 + w_coarse*(1-F325) + w_low_lib*(1-Liberation_gangue) + w_density*abs(C-C_opt) + w_clay*clay`

### `fx_s{s}_{c}_froth_h`
- line 875: 7. 浮选因果模型 / 7.5 气量和泡沫控制 -> `fx_s{s}_{c}_froth_h =`
- line 1679: 10. DCS 具体生成公式和代理防护 / 10.4 浮选 DCS 具体公式 -> `fx_s{s}_{c}_froth_h=meas(h_froth_{s,c}) unless event_froth_fault_{s,c}=1`

### `grind_difficulty`
- line 641: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `grind_difficulty = kWI*(WI_mill-WI_ref) + kcoarse*(1-F325_sand) + kC*(C_mill-C_opt)^2 + kmu*(mu_slurry-mu_ref) + kCL*(circulating_load-CL_ref)`
- line 1363: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `grind_difficulty = kWI*(WI_mill-WI_ref) + kcoarse*(1-F325_sand) + kC*(C_mill-C_opt)^2 + kmu*(mu_feed-mu_ref) + kCL*(circulating_load-CL_ref)`

### `inst_circ_load`
- line 634: 6. 塔磨与旋流器因果模型 / 6.3 塔磨功耗和解离 -> `inst_circ_load=M_sand/max(M_overflow,eps)`
- line 1356: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `inst_circ_load = M_sand/max(M_overflow,eps)`

### `magnetic_difficulty`
- line 461: 5. 磁选因果模型 / 5.2 控制设定不得孤立 -> `magnetic_difficulty = w_low_mag*(r_mag_ref-r_mag) + w_low_lib*(1-Liberation_fe) + w_coarse*(1-F200) + w_load*(Q_feed-Q_ref) + w_carb*r_carb + w_sil*r_sil`
- line 1207: 10. DCS 具体生成公式和代理防护 / 10.2 磁选 DCS 具体公式 -> `magnetic_difficulty = w_low_mag*clip(r_mag_ref-r_mag,0,1) + w_low_lib*(1-Liberation_fe) + w_coarse*(1-F200) + w_load*(Q_feed-Q_ref)/max(Q_ref,eps) + w_harmful*(r_carb+r_sil)`

### `matrix_clog`
- line 505: 5. 磁选因果模型 / 5.2 控制设定不得孤立 -> `matrix_clog = clip(matrix_clog_prev+dt*(clog_buildup-clog_wash),0,1)`
- line 1233: 10. DCS 具体生成公式和代理防护 / 10.2 磁选 DCS 具体公式 -> `matrix_clog = clip(matrix_clog_prev+dt*(clog_buildup-clog_wash),0,1)`

### `rho_overflow`
- line 611: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `rho_overflow = (M_overflow_solid+M_overflow_water)/max(Q_overflow,eps)`
- line 1340: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `rho_overflow = (M_tm_overflow_solid+M_tm_overflow_water)/max(Q_overflow,eps)`

### `tau_cyc_pool`
- line 581: 6. 塔磨与旋流器因果模型 / 6.2 泵池与旋流器 -> `tau_cyc_pool=max(L_pool*A_pool/max(Q_pump,eps),min_tau_cyc_pool)`
- line 1290: 10. DCS 具体生成公式和代理防护 / 10.3 塔磨 DCS 具体公式 -> `tau_cyc_pool = max(L_pool*A_pool/max(Q_pump_prev,eps),min_tau_cyc_pool)`

## Listed DCS Without Explicit `meas(...)`

- `agg_mag_tailings_valve1/2` (line 548 5. 磁选因果模型/5.4 磁选 DCS 变量)
- `cao}_curr` (line 793 7. 浮选因果模型/7.3 药剂控制)
- `cao}_freq` (line 792 7. 浮选因果模型/7.3 药剂控制)
- `fx_s{s}_cao_curr` (line 1007 7. 浮选因果模型/7.8 浮选 DCS 变量模板)
- `fx_s{s}_cao_freq` (line 1006 7. 浮选因果模型/7.8 浮选 DCS 变量模板)
- `fx_s{s}_k6_rough_curr` (line 1003 7. 浮选因果模型/7.8 浮选 DCS 变量模板)
- `fx_s{s}_k6_rough_freq` (line 1002 7. 浮选因果模型/7.8 浮选 DCS 变量模板)
- `fx_s{s}_naoh_curr` (line 1005 7. 浮选因果模型/7.8 浮选 DCS 变量模板)
- `fx_s{s}_naoh_freq` (line 1004 7. 浮选因果模型/7.8 浮选 DCS 变量模板)
- `fx_s{s}_td_clean_curr` (line 1001 7. 浮选因果模型/7.8 浮选 DCS 变量模板)
- `fx_s{s}_td_clean_freq` (line 1000 7. 浮选因果模型/7.8 浮选 DCS 变量模板)
- `fx_s{s}_td_rough_curr` (line 999 7. 浮选因果模型/7.8 浮选 DCS 变量模板)
- `fx_s{s}_td_rough_freq` (line 998 7. 浮选因果模型/7.8 浮选 DCS 变量模板)

## Explicit `meas(...)` Not Listed In DCS Tables

- `agg_mag_tailings_valve1` (line 1277 10. DCS 具体生成公式和代理防护/10.2 磁选 DCS 具体公式 <- `u_tail`)
- `agg_mag_tailings_valve2` (line 1278 10. DCS 具体生成公式和代理防护/10.2 磁选 DCS 具体公式 <- `u_tail_2`)
- `agg_tm_cyclone_feed_pressure` (line 1410 10. DCS 具体生成公式和代理防护/10.3 塔磨 DCS 具体公式 <- `P_cyc`)
- `fx_s{s}_{drug}_curr` (line 1688 10. DCS 具体生成公式和代理防护/10.4 浮选 DCS 具体公式 <- `I_drug_j_phys_{s,drug}`)
- `fx_s{s}_{drug}_freq` (line 1687 10. DCS 具体生成公式和代理防护/10.4 浮选 DCS 具体公式 <- `f_{s,drug}`)
