from MCP.mcp_asset_scope import asset_targets, conflicting_packages


class AssetCoordination:
    """
    /**
     * 维护资产占用的唯一登记簿 由队列条件锁保护
     */
    """

    def __init__(self):
        """/** @return 空资产登记簿 */"""
        self.claims = {}

    def hold(self, batch, packages, phase):
        """/** @param batch\t所属批次 @param packages\t包或目录范围 @param phase\t当前阶段 @return 更新后的占用 */"""
        scope = asset_targets(packages)
        if scope:
            attempts = self.claims.get(batch, {}).get("attempts", 0)
            self.claims[batch] = {"packages": sorted(scope), "phase": phase, "attempts": attempts}
        if not scope:
            self.release(batch)
        return self.claims.get(batch)

    def release(self, batch):
        """/** @param batch\t所属批次 @return 释放资产范围 */"""
        self.claims.pop(batch, None)

    def fault(self, batch, packages, code, now):
        """/** @param batch\t所属批次 @param packages\t故障资产 @param code\t实际原因 @param now\t当前时间 @return 自动恢复安排 */"""
        attempts = self.claims.get(batch, {}).get("attempts", 0) + 1
        self.hold(batch, packages, "fault")
        if batch in self.claims:
            retry_at = now + min(60, 2 ** min(attempts, 6))
            if attempts >= 4 or code in {"MOVE_HOST_CHANGED", "MOVE_SOURCE_CHANGED", "MOVE_SOURCE_STATE_REQUIRED", "MOVE_TARGET_CHANGED", "MOVE_REFERENCER_REQUIRED", "MOVE_RECOVERY_INVALID", "MOVE_RECOVERY_GUARD"}:
                retry_at = None
            self.claims[batch].update(code=code, attempts=attempts, retry_at=retry_at)

    def due(self, now):
        """/** @param now\t当前时间 @return 到期的资产恢复批次 */"""
        return next((batch for batch, claim in self.claims.items() if claim["phase"] == "fault" and claim["retry_at"] is not None and claim["retry_at"] <= now), None)

    def conflicts(self, batch, packages):
        """/** @param batch\t申请批次 @param packages\t目标范围 @return 按占用顺序排列的实际冲突 */"""
        conflicts = []
        for identity, claim in self.claims.items():
            if identity == batch:
                continue
            overlap = conflicting_packages(claim["packages"], packages)
            if overlap:
                conflicts.append({"batch": identity, "packages": sorted(overlap), "phase": claim["phase"], "code": claim.get("code")})
        return conflicts

    def view(self, batch):
        """/** @param batch\t所属批次 @return 可持久化的占用证据 */"""
        claim = self.claims.get(batch)
        if claim is None:
            return {"packages": [], "phase": "released"}
        return {**claim, "packages": list(claim["packages"])}
