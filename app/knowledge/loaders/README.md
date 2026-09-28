# app/knowledge/loaders/ —— 文档解析器

统一接口（架构设计 6.2）：`parse(file_path) -> ParsedDocument`，`Block` 必须携带可溯源位置：

| 解析器 | 格式 | 位置元数据 | 注意事项 |
| :--- | :--- | :--- | :--- |
| `pdf_loader.py` | `.pdf` | `page_no` | 扫描件无文本层 → 写入 `warnings`（提示暂不支持 OCR） |
| `docx_loader.py` | `.docx` | `section`（标题路径）/ 页码 | 老版 `.doc` 提示另存为 `.docx` |
| `xlsx_loader.py` | `.xlsx` | `sheet_name` + `row_start/row_end` | 首行表头、公式未计算时跳过并告警 |
| `txt_loader.py` | `.txt` | `row_start/row_end` | chardet 识别 UTF-8/GBK，置信度低时依次尝试 |
| `md_loader.py` | `.md` | `section` + 行号 | 按标题层级切片 |

`registry.py` 负责「扩展名 → 解析器」路由；未知扩展名抛业务错误 `1002`（接口文档 1.4）。
