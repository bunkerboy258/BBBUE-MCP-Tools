import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_call import _parse_response


class McpSseStreamTests(unittest.TestCase):
    """/** 分块读取必须兼顾大消息与未关闭的小事件流 */"""

    def parse(self, chunks, changed=None):
        """/** @param chunks 明确字节分块 @param changed 通知回调 @return 实际协议结果 */"""
        response = Mock()
        response.headers = {"Content-Type": "text/event-stream"}
        response.raw.read1.side_effect = chunks
        result = _parse_response(response, 7, changed or Mock())
        response.raw.read1.assert_called_with(65536, decode_content=True)
        return result

    def test_small_event_returns_without_waiting_for_stream_close(self):
        """/** @return 小事件结束即返回 不需要凑满缓冲区 */"""
        self.assertEqual(self.parse([b'data: {"id":7,"result":true}\n\n'])["result"], True)

    def test_utf8_character_split_across_chunks(self):
        """/** @return 跨块中文仍可完整解码 */"""
        message = 'data: {"id":7,"result":"骨骼"}\r\n\r\n'.encode("utf-8")
        self.assertEqual(self.parse([message[:26], message[26:27], message[27:]])["result"], "骨骼")

    def test_large_pose_message(self):
        """/** @return 大姿势消息按分块处理 保持原始内容 */"""
        result = {"id": 7, "result": "x" * 2000000}
        message = ("data: " + json.dumps(result) + "\n\n").encode()
        self.assertEqual(self.parse([message[index:index + 65536] for index in range(0, len(message), 65536)]), result)

    def test_notification_before_matching_response(self):
        """/** @return 工具变更通知不会吞掉目标响应 */"""
        changed = Mock()
        result = self.parse([b'data: {"method":"notifications/tools/list_changed"}\n\ndata: {"id":7,"result":true}\n\n'], changed)
        changed.assert_called_once_with()
        self.assertTrue(result["result"])

    def test_truncated_stream_is_rejected(self):
        """/** @return 不完整事件不能冒充已完成结果 */"""
        with self.assertRaisesRegex(RuntimeError, "未收到"):
            self.parse([b'data: {"id":7,"result":true}\n', b""])


if __name__ == "__main__":
    unittest.main()
