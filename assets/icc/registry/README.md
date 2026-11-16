# ICC 注册签名快照

2026-11-16 从 [ICC 官方注册站](https://registry.color.org/)取得 CMM、厂商及设备 CSV，选取签名列，未保存联系人资料。`SOURCE.json` 记录下载地址、原始下载 SHA-256、所选数据 SHA-256 及数量。ICC 数据版权归 International Color Consortium；这里只保存注册标识事实。

`tools/generate_icc_registry.py` 生成纯 Python 查找表，不需要运行时联网。设备列保留原始 `文本-十六进制`，没有自动修复原站缺位或不一致的编码；有歧义的条目单独记录。未确认的签名报告 `PngUnsupportedError`，不能根据快照缺失断言它从未注册。更新时重新选取同样的 CSV 列、更新来源与摘要并重新生成。

ICC.1:2022 7.2.3、7.2.12、7.2.13 要求非零 CMM、厂商和型号是注册签名；7.2.17 对 creator 使用建议措辞，因此不因 creator 未注册而拒绝。快照核实不证明文件对应真实设备或实际由该厂商生成。

`characterization.json` 另选取同日 CMYK Characterization Data 表的 56 个 Reference name，供 `ICCHDAT` 引用核实；内部空格和大小写保留。原始页面及所选数据摘要见同一来源记录。
