import hashlib
from pathlib import Path
import threading
import importlib.abc
import importlib.machinery
import sys
import time


_lock = threading.Lock()
_signature = None
_digest = None
_checked_at = 0
_file_digests = {}


def source_version(force=False):
    """/** @return 当前 Scripts 源码内容版本 */"""
    global _signature, _digest, _checked_at, _file_digests
    root = Path(__file__).resolve().parents[1]
    with _lock:
        if not force and _digest is not None and time.monotonic() - _checked_at < 1:
            return _digest
        files = sorted(root.rglob("*.py"))
        signature = []
        for path in files:
            metadata = path.stat()
            signature.append((str(path.relative_to(root)), metadata.st_mtime_ns, metadata.st_ctime_ns, metadata.st_size))
        signature = tuple(signature)
        if force or signature != _signature:
            digest = hashlib.sha256()
            file_digests = {}
            for entry in signature:
                path = entry[0]
                content = _file_digests.get(entry)
                if content is None or force:
                    content = hashlib.sha256((root / path).read_bytes()).digest()
                file_digests[entry] = content
                digest.update(path.encode("utf-8"))
                digest.update(b"\0")
                digest.update(content)
            _digest = digest.hexdigest()
            _signature = signature
            _file_digests = file_digests
        _checked_at = time.monotonic()
        return _digest


class SourceLoader(importlib.machinery.SourceFileLoader):
    """/** 仓库模块始终从源文件编译 */"""

    def get_code(self, fullname):
        """/** @param fullname 模块名 @return 当前源文件的代码对象 */"""
        return self.source_to_code(self.get_data(self.path), self.path)


class SourceFinder(importlib.abc.MetaPathFinder):
    """/** 仅接管本仓库的 Python 源码 */"""

    def find_spec(self, fullname, path=None, target=None):
        """/** @param fullname 模块名 @param path 包路径 @param target 重载目标 @return 仓库源码加载器 */"""
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or not spec.origin or not spec.origin.endswith(".py"):
            return None
        root = Path(__file__).resolve().parents[1]
        if Path(spec.origin).resolve().is_relative_to(root):
            spec.loader = SourceLoader(fullname, spec.origin)
            return spec
        return None


def install_source_loader():
    """/** @return 安装一次仓库源码加载器 */"""
    if not any(isinstance(item, SourceFinder) for item in sys.meta_path):
        sys.meta_path.insert(0, SourceFinder())
