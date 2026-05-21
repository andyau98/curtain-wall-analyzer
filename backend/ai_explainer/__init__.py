"""
AI 講解層 — 使用 Claude API 將結構分析結果轉為人可讀的專業解說。
只在用戶需要時調用，不參與自動分析流程。
"""

import json
import os
from anthropic import Anthropic


class AIExplainer:
    """
    將規則引擎的結構化分析結果，轉化為專業的幕牆工程解說。
    支援兩種模式:
      - 位置圖解說: 說明軸網、面板分佈、尺寸系統
      - 加工圖解說: 說明加工標記、公差要求、組裝順序
    """

    def __init__(self, api_key: str = None):
        self.client = Anthropic(api_key=api_key or os.getenv('ANTHROPIC_API_KEY'))

    def explain_position_drawing(self, analysis_result: dict, lang: str = 'zh') -> str:
        """解釋位置圖的結構。"""
        prompt = self._build_position_prompt(analysis_result, lang)
        return self._call_claude(prompt)

    def explain_fabrication_drawing(self, analysis_result: dict, lang: str = 'zh') -> str:
        """解釋加工圖的結構。"""
        prompt = self._build_fabrication_prompt(analysis_result, lang)
        return self._call_claude(prompt)

    def explain_drawing_structure(self, analysis_result: dict, lang: str = 'zh') -> str:
        """自動判斷圖紙類型並給出適當解說。"""
        drawing_type = analysis_result.get('drawing_type', 'position')
        if drawing_type == 'fabrication':
            return self.explain_fabrication_drawing(analysis_result, lang)
        else:
            return self.explain_position_drawing(analysis_result, lang)

    # -----------------------------------------------------------------
    def _build_position_prompt(self, data: dict, lang: str) -> str:
        grid = data.get('grid_system', {})
        panels = data.get('panel_layout', {})
        summary = data.get('summary', {})

        return f"""你是一位資深幕牆工程顧問。請根據以下位置圖 (Setting-out / Layout Drawing) 的結構分析結果，用{'繁體中文' if lang == 'zh' else 'English'}為工程師講解這張圖紙的結構。

## 圖紙結構數據

### 基本資訊
- 圖紙類型: {data.get('drawing_type', '未知')}
- 圖面尺寸: {data.get('image_size', '未知')} px
- DPI: {data.get('dpi', 300)}

### 軸網系統
- 總軸線數: {grid.get('total_axes', 0)}
- 水平軸線: {len(grid.get('horizontal_axes', []))} 條
- 垂直軸線: {len(grid.get('vertical_axes', []))} 條
- 跨數 (格數): {grid.get('bay_count', 0)}
- 交點數: {grid.get('intersection_count', 0)}

### 面板佈局
- 總面板數: {panels.get('total_panels', 0)}
- 類型分佈: {json.dumps(panels.get('type_summary', {}), ensure_ascii=False)}
- 長寬比分佈: {json.dumps(panels.get('aspect_summary', {}), ensure_ascii=False)}

### 標註
- 尺寸標註: {len(data.get('annotations', {}).get('dimensions', []))} 組
- 文字區域: {len(data.get('annotations', {}).get('text_regions', []))} 個
- 加工標記: {len(data.get('annotations', {}).get('fab_marks', []))} 個

### 摘要
{summary.get('text', '')}

請依以下架構講解：

1. **圖紙類型與用途** — 這張圖在幕牆工程中扮演什麼角色
2. **軸網結構** — 軸線編號規則、跨距規律、是否有偏心或不規則處
3. **面板分佈** — 面板類型配置邏輯 (哪些區域是視野玻璃、背襯面板、可開啟窗等)
4. **尺寸系統** — 標註方式、基準線設定、關鍵控制尺寸
5. **加工資訊** — 位置圖上標註的加工要求 (如有)
6. **檢查要點** — 審圖時應特別注意的地方

請用專業但易於理解的語氣，適合有 3-5 年經驗的幕牆工程師閱讀。"""

    def _build_fabrication_prompt(self, data: dict, lang: str) -> str:
        annotations = data.get('annotations', {})
        summary = data.get('summary', {})

        return f"""你是一位資深幕牆加工顧問。請根據以下加工圖 (Fabrication / Shop Drawing) 的結構分析結果，用{'繁體中文' if lang == 'zh' else 'English'}為工程師講解這張加工圖的內容。

## 圖紙結構數據

### 基本資訊
- 圖紙類型: {data.get('drawing_type', '未知')}
- 圖面尺寸: {data.get('image_size', '未知')} px

### 加工標記
- 標記總數: {annotations.get('fab_mark_count', 0)}
- 詳情: {json.dumps(annotations.get('fab_marks', []), ensure_ascii=False)}

### 尺寸標註
- 尺寸標註數: {annotations.get('dimension_count', 0)}
- 詳情: {json.dumps(annotations.get('dimensions', []), ensure_ascii=False)}

### 文字標註
- 文字區域數: {annotations.get('text_region_count', 0)}

### 摘要
{summary.get('text', '')}

請依以下架構講解：

1. **加工圖類型** — 這是單元圖、組裝圖還是零件圖
2. **加工標記解讀** — 各符號的意義 (焊接、切割、鑽孔、開槽、折彎)
3. **關鍵尺寸與公差** — 哪些尺寸需要特別控制
4. **材料與表面處理** — 標註中提到的材料和處理要求
5. **組裝順序** — 從加工圖推斷的組裝邏輯
6. **品質檢查要點** — QC 應重點檢查的項目

請用專業但易於理解的語氣。"""

    def _call_claude(self, prompt: str) -> str:
        try:
            msg = self.client.messages.create(
                model='claude-sonnet-4-6',
                max_tokens=2048,
                temperature=0.3,
                messages=[{'role': 'user', 'content': prompt}],
            )
            return msg.content[0].text
        except Exception as e:
            return f"[AI 講解暫時不可用: {e}]\n\n請改用規則引擎的自動分析結果。"
