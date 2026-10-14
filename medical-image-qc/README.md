# Medical Image QC

三维医学影像数据质量检查工具。面向多模态 NIfTI 数据，在进入分割训练前发现文件缺失、模态不完整、空间信息不一致和基础像素异常。使用 Python、NumPy、NiBabel；仅需 CPU。

**项目状态：2026 年 10 月新建的 AI 辅助开发学习项目。** 初始实现、测试和文档由 AI 编程助手协助完成，维护者需要理解并持续验证代码。它是医学影像分割学习的配套工程工具，不是 SegMamba 原创方法，也没有完成临床或真实队列验证。公开演示全部使用程序生成的合成体数据，不包含患者数据。

## 快速运行

Python 3.10 或更高版本。推荐在单独的虚拟环境中安装。

```bash
git clone https://github.com/YeY-zi/3d-medical-segmentation-mamba.git
cd 3d-medical-segmentation-mamba/medical-image-qc
python -m pip install -r requirements.txt
python make_demo.py
python audit.py demo-data/manifest.json --out reports
python -m unittest -v test_audit
```

打开 `reports/report.html` 查看报告；`reports/report.json` 用于进一步分析。示例故意包含异常数据，因此审计命令返回 **1** 属于预期行为。退出码：0 为没有 fail（允许 warn），1 为发现 fail，2 为清单或输入输出错误。

## 演示结果

运行固定随机种子的 `make_demo.py` 生成五组数据，得到以下结果。这里的结果是软件功能验证，不是医学模型性能指标。

| 合成案例 | 预期状态 | 主要原因 |
|---|---|---|
| healthy_input | pass | 模态和空间结构满足本工具检查条件；名称不代表临床健康 |
| missing_flair | fail | 未提供 flair 模态 |
| shifted_geometry | fail | t2 的空间平移与其他模态不一致 |
| nonfinite_data | fail | t1 含 NaN |
| constant_image | warn | t1 为常量图像 |

已保存可复现输出：[`examples/report.json`](examples/report.json) 和 [`examples/report.html`](examples/report.html)。下载 HTML 后用浏览器打开。初始版本在 Windows / Python 3.12.14 环境下通过 15 项 unittest 检查。

## 如何使用自己的数据

使用显式清单标明模态，不通过文件名猜测其医学含义。路径相对于清单文件所在目录，不能指向其上级目录。可以嵌套任意子目录；不要求 BraTS 特定命名。

```json
{
  "cases": [
    {
      "id": "case_001",
      "modalities": {
        "t1": "case_001/t1.nii.gz",
        "t1ce": "case_001/t1ce.nii.gz",
        "t2": "case_001/t2.nii.gz",
        "flair": "case_001/flair.nii.gz"
      }
    }
  ]
}
```

```bash
python audit.py /path/to/data/manifest.json --out reports
# 可按其他数据集要求自定义模态名
python audit.py /path/to/data/manifest.json --expected t1n,t1c,t2w,t2f --out reports
```

## 检查范围

- 清单：非空 cases、唯一案例 ID、路径及模态映射格式。
- 文件：存在性、NIfTI 扩展名、能否读取、是否为非空三维体数据。
- 空间信息：affine 的有限性和非奇异性、体素间距、方向码、空间单位；同一案例中预期模态的 shape、单位和 affine 是否一致。
- qform/sform：两者都有有效 code 且不一致时警告；没有带 code 的空间变换时警告。
- 像素：NaN/Inf 检查及有限值比例；常量图像警告。
- 容量：每张图默认最多 50,000,000 个体素，超限记为 fail 且跳过像素载入；可用 `--max-voxels` 调整。
- 输出：JSON 与 HTML；病例 ID 与异常信息在 HTML 中转义；不导出绝对路径和其他 NIfTI 自由文本头信息。

affine 比较使用绝对容差 1e-4、相对容差 0，按文件原始空间单位比较，不自动转换单位。参考模态为 `--expected` 顺序中第一个具有可用 affine 的模态。单个文件损坏不会终止其他案例的审计。

## 重要边界

一致的 affine 和 shape **不能证明图像在解剖上正确配准**。工具不会判断病灶、图像诊断价值或患者身份，也不会计算 Dice、HD95，不提供自动重采样。非有限值、常量图像及元数据检查仅能筛查部分输入问题。

像素检查使用 float32，检查的是该载入精度下的值。3D 图像会逐张读取并计算统计信息；体素上限是资源控制措施，不是对任意损坏或恶意文件的完整防护。报告保留清单中的案例 ID，分享真实数据报告前请使用匿名编号。

## 文件说明

- `audit.py`：清单校验、单体检查、跨模态比较、JSON/HTML 报告及 CLI。
- `make_demo.py`：固定随机种子的合成数据生成器。
- `test_audit.py`：15 项功能和边界检查。
- `examples/`：实际生成的合成演示报告。
- `LEARNING_GUIDE.md`：阅读顺序、可解释性问题与下一步实验。

## 后续计划

在明确许可的数据上验证误报与漏报，补充文件截断、各向异性和复杂空间变换测试；探索轻量可视化预览及数据集级统计。上述属于待开展工作，不是当前实现功能。

## 参考

- [NiBabel NIfTI 文档](https://nipy.org/nibabel/nifti_images.html)：NIfTI 头信息与空间变换。
- [SegMamba 原作者仓库](https://github.com/ge-xing/SegMamba)：本仓库原有分割学习背景来源。本子项目不复制其模型实现。

本目录代码按 MIT License 提供，见 `LICENSE`。不改变仓库其他内容或上游项目的许可。
