import json
from pathlib import Path
import sys

from BBBGripVisualReview import hand_triangles, render


def main():
    """/** @return 复用原彩色三视图绘制器输出实际蒙皮手部 无武器接触验收 */"""
    source = Path(sys.argv[1]).resolve()
    sample = json.loads(source.read_text(encoding='utf-8-sig'))
    if not sample.get('readOnly') or not source.is_file():
        raise ValueError('FINGER_VISUAL_NATIVE_SAMPLE_REQUIRED')
    results = []
    for side in ('left', 'right'):
        triangles, unused = hand_triangles(sample, side, True)
        destination = source.with_name(source.stem + '_' + side + '.png')
        render(triangles, [], destination, side)
        results.append(str(destination))
    print(json.dumps(results))


if __name__ == '__main__':
    main()
