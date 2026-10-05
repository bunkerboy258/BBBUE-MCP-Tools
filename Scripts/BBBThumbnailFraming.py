import math


def frame_alpha_image(image, occupancy=0.86, size=512):
    """
    /**
     * 按真实不透明像素统一缩略图的占幅 保留原始颜色与长宽比
     * @param image\t带透明通道的原始渲染
     * @param occupancy\t主体最长边的目标占幅
     * @param size\t输出边长
     * @return 重新取景的图像与像素边界
     */
    """
    from PIL import Image

    if not math.isfinite(occupancy) or not 0.65 <= occupancy <= 0.94:
        raise ValueError("主体占幅必须位于零点六五到零点九四")
    if size not in (256, 512, 1024):
        raise ValueError("缩略图尺寸必须为二百五十六 五百一十二或一千零二十四")
    if image.mode != "RGBA":
        raise ValueError("缩略图必须包含透明通道")
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] > 8:
        raise ValueError("缩略图没有透明背景 禁止按整图误判主体")
    bounds = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
    if bounds is None:
        raise ValueError("缩略图没有可见主体")
    subject = image.crop(bounds)
    scale = size * occupancy / max(subject.size)
    dimensions = tuple(max(1, round(value * scale)) for value in subject.size)
    subject = subject.resize(dimensions, Image.Resampling.LANCZOS)
    output = Image.new("RGBA", (size, size))
    output.alpha_composite(subject, ((size - dimensions[0]) // 2, (size - dimensions[1]) // 2))
    return output, bounds


if __name__ == "__main__":
    import json
    from pathlib import Path
    import sys
    from PIL import Image

    source = Path(sys.argv[1]).resolve()
    if source.suffix.lower() != ".png" or source.parent.parent.name != "ThumbnailFraming":
        raise ValueError("只允许处理本工具导出的临时 PNG")
    with Image.open(source) as original:
        framed, bounds = frame_alpha_image(original.convert("RGBA"), float(sys.argv[2]))
    framed.save(source)
    print(json.dumps({"bounds": bounds}))
