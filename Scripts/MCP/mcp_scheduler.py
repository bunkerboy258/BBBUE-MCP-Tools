def ordered(records, operators):
    """/** @param records 候选任务 @param operators 干员登记 @return 按等级和等待顺序排列的候选 */"""
    return sorted(records, key=lambda row: (operators.level(row["owner"]), row["submitted_at"], row.get("id", row.get("batch", ""))))
