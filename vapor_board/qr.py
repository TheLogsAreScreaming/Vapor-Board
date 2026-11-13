"""Minimal QR code encoder (byte mode, error correction level M, versions 1–20).

Hand-written so the app needs no third-party packages; used to show phone pairing links.
Follows ISO/IEC 18004. Tests compare the output with the `segno` package when it is installed.
"""

# Level M tables, indexed by version (index 0 unused).
_ECC_PER_BLOCK = (None, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26)
_BLOCKS = (None, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16)
_FORMAT_LEVEL_M = 0
MAX_VERSION = 20


def _raw_modules(version):
    result = (16 * version + 128) * version + 64
    if version >= 2:
        count = version // 7 + 2
        result -= (25 * count - 10) * count - 55
        if version >= 7:
            result -= 36
    return result


def _data_codewords(version):
    return _raw_modules(version) // 8 - _ECC_PER_BLOCK[version] * _BLOCKS[version]


def _alignment_positions(version, size):
    if version == 1:
        return []
    count = version // 7 + 2
    step = (version * 4 + count * 2 + 1) // (count * 2 - 2) * 2
    return [6] + [size - 7 - i * step for i in range(count - 1)][::-1]


# ---- Reed–Solomon over GF(256), polynomial 0x11D -------------------------------------------
def _gf_multiply(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_multiply(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coefficient in enumerate(divisor):
            result[i] ^= _gf_multiply(coefficient, factor)
    return result


# ---- data -------------------------------------------------------------------------------
def _codewords(data, version):
    count_bits = 8 if version <= 9 else 16
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in range(count_bits - 1, -1, -1)]
    for byte in data:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    capacity = _data_codewords(version) * 8
    bits += [0] * min(4, capacity - len(bits))
    bits += [0] * (-len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < capacity // 8:
        words.append(pad)
        pad ^= 0xEC ^ 0x11

    blocks, ecc_len = _BLOCKS[version], _ECC_PER_BLOCK[version]
    raw = _raw_modules(version) // 8
    short_blocks, short_len = blocks - raw % blocks, raw // blocks
    divisor = _rs_divisor(ecc_len)
    split, index = [], 0
    for i in range(blocks):
        size = short_len - ecc_len + (0 if i < short_blocks else 1)
        chunk = words[index:index + size]
        index += size
        ecc = _rs_remainder(chunk, divisor)
        if i < short_blocks:
            chunk = chunk + [None]
        split.append(chunk + ecc)
    return [block[i] for i in range(len(split[0])) for block in split if block[i] is not None]


def _version_for(length):
    for version in range(1, MAX_VERSION + 1):
        count_bits = 8 if version <= 9 else 16
        if 4 + count_bits + 8 * length <= _data_codewords(version) * 8 and length < (1 << count_bits):
            return version
    raise ValueError(f"text too long for a version {MAX_VERSION} QR code")


# ---- the symbol -------------------------------------------------------------------------
_MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


class _Symbol:
    def __init__(self, version):
        self.version = version
        self.size = version * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.function = [[False] * self.size for _ in range(self.size)]

    def set_function(self, x, y, dark):
        self.dark[y][x] = bool(dark)
        self.function[y][x] = True

    def draw_function_patterns(self):
        size = self.size
        for i in range(size):
            self.set_function(6, i, i % 2 == 0)
            self.set_function(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        self.set_function(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        positions = _alignment_positions(self.version, size)
        last = len(positions) - 1
        for i, cx in enumerate(positions):
            for j, cy in enumerate(positions):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_function(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)
        if self.version >= 7:
            remainder = self.version
            for _ in range(12):
                remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
            bits = self.version << 12 | remainder
            for i in range(18):
                bit, a, b = (bits >> i) & 1, size - 11 + i % 3, i // 3
                self.set_function(a, b, bit)
                self.set_function(b, a, bit)

    def draw_format(self, mask):
        data = _FORMAT_LEVEL_M << 3 | mask
        remainder = data
        for _ in range(10):
            remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
        bits = (data << 10 | remainder) ^ 0x5412
        bit = lambda i: (bits >> i) & 1
        size = self.size
        for i in range(6):
            self.set_function(8, i, bit(i))
        self.set_function(8, 7, bit(6))
        self.set_function(8, 8, bit(7))
        self.set_function(7, 8, bit(8))
        for i in range(9, 15):
            self.set_function(14 - i, 8, bit(i))
        for i in range(8):
            self.set_function(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_function(8, size - 15 + i, bit(i))
        self.set_function(8, size - 8, True)

    def draw_codewords(self, words):
        size, index, total = self.size, 0, len(words) * 8
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vertical in range(size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = size - 1 - vertical if upward else vertical
                    if not self.function[y][x] and index < total:
                        self.dark[y][x] = bool((words[index >> 3] >> (7 - (index & 7))) & 1)
                        index += 1
            right -= 2

    def apply_mask(self, mask):
        rule = _MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.function[y][x] and rule(x, y):
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self):
        size, grid, score = self.size, self.dark, 0
        lines = grid + [[grid[y][x] for y in range(size)] for x in range(size)]
        finder_like = ([True, False, True, True, True, False, True, False, False, False, False],
                       [False, False, False, False, True, False, True, True, True, False, True])
        for line in lines:
            run = 1
            for i in range(1, size + 1):
                if i < size and line[i] == line[i - 1]:
                    run += 1
                    continue
                if run >= 5:
                    score += 3 + run - 5
                run = 1
            for i in range(size - 10):
                if line[i:i + 11] in finder_like:
                    score += 40
        for y in range(size - 1):
            for x in range(size - 1):
                if grid[y][x] == grid[y][x + 1] == grid[y + 1][x] == grid[y + 1][x + 1]:
                    score += 3
        dark = sum(map(sum, grid))
        total = size * size
        score += ((abs(dark * 20 - total * 10) + total - 1) // total - 1) * 10
        return score


def encode(text, mask=None):
    """Rows of booleans (True = dark), without the quiet zone. Picks the best mask unless given."""
    data = text.encode("utf-8")
    version = _version_for(len(data))
    words = _codewords(data, version)
    best = None
    for candidate in ([mask] if mask is not None else range(8)):
        symbol = _Symbol(version)
        symbol.draw_function_patterns()
        symbol.draw_codewords(words)
        symbol.apply_mask(candidate)
        symbol.draw_format(candidate)
        score = symbol.penalty()
        if best is None or score < best[0]:
            best = (score, symbol)
    return best[1].dark
