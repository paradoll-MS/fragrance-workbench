同一子项目的字段 <field> 有两份不一致的判断。只判断这个字段。

判断 1：<value1>
依据 1：<quote1>（<locator1>）
判断 2：<value2>
依据 2：<quote2>（<locator2>）

原文片段：
<excerpts>

输出 json：
{"value":<采用的值>,"quote":"<支撑它的原文片段>","locator":"<位置>"}
如果原文两份都不支持，输出 {"value":null,"quote":"","locator":""}。
不要解释，不要重写其它字段。
