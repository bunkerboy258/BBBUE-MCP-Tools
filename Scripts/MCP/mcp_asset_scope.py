import re


def asset_targets(value, normalize=True):
    """/** @param value\t操作参数 @param normalize\t规范化为包路径 @return 明确的目标集合 */"""
    targets = set()
    if isinstance(value, str) and value.startswith("/Game/"):
        # PIE 临时包由运行宿主持有 不属于磁盘资产或源控写入范围
        if re.search(r"/UEDPIE_[0-9]+_[^/]+(?:$|/)", value.split(".", 1)[0]):
            return targets
        targets.add(value.split(".", 1)[0].split(":", 1)[0].rstrip("/") if normalize else value)
    if isinstance(value, dict):
        for item in value.values():
            targets.update(asset_targets(item, normalize))
    if isinstance(value, (list, tuple, set)):
        for item in value:
            targets.update(asset_targets(item, normalize))
    return targets


def conflicting_packages(packages, scope):
    """
    /**
     * @param packages	待核对包路径
     * @param scope	明确包或目录范围
     * @return 与范围相交的包 保留原始大小写
     */
    """
    roots = {path.casefold() for path in asset_targets(scope)}
    candidates = asset_targets(packages)
    def variants(path):
        values = {path.casefold()}
        for prefix in ("/Game/__ExternalActors__/", "/Game/__ExternalObjects__/"):
            if path.casefold().startswith(prefix.casefold()):
                values.add(("/Game/" + path[len(prefix):]).casefold())
        return values
    return {
        package for package in candidates
        if any(candidate == target or candidate.startswith(target + "/") or target.startswith(candidate + "/")
            for candidate in variants(package) for root in roots for target in variants(root))
    }
