// Grayscale SVG boards for the white-on-black page. The move played is a dark
// arrow and the engine's best move a white arrow.

import { Chess } from '../vendor/chess.js';
import { PIECES } from './pieces.js';

const LIGHT = '#d0d0d0', DARK = '#7a7a7a';
const PLAYED = 'rgba(0,0,0,0.8)', BEST = 'rgba(255,255,255,0.8)';
const SQ = 45, MARGIN = 20;

function xy(square, flip) {
  const file = square.charCodeAt(0) - 97, rank = +square[1] - 1;
  const col = flip ? 7 - file : file, row = flip ? rank : 7 - rank;
  return [MARGIN + col * SQ, MARGIN + row * SQ];
}

function arrow(from, to, color, flip) {
  const [x1, y1] = xy(from, flip).map(v => v + SQ / 2);
  const [x2, y2] = xy(to, flip).map(v => v + SQ / 2);
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len;
  const head = 18, w = 7, hw = 15;
  const bx = x2 - ux * head, by = y2 - uy * head;
  const px = -uy, py = ux;
  const pts = [
    [x1 + px * w / 2, y1 + py * w / 2], [bx + px * w / 2, by + py * w / 2], [bx + px * hw / 2, by + py * hw / 2], [x2, y2],
    [bx - px * hw / 2, by - py * hw / 2], [bx - px * w / 2, by - py * w / 2], [x1 - px * w / 2, y1 - py * w / 2],
  ];
  return `<polygon points="${pts.map(p => p.map(v => v.toFixed(1)).join(',')).join(' ')}" fill="${color}"/>`;
}

// fen: the position to draw. played/best: UCI strings or null. orientation: 'white' | 'black'.
export function boardSvg(fen, { played = null, best = null, orientation = 'white', size = 400 } = {}) {
  const flip = orientation === 'black';
  const total = SQ * 8 + MARGIN * 2;
  const parts = [`<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 ${total} ${total}" width="${size}" height="${size}" role="img">`];
  parts.push(`<defs>${Object.values(PIECES).join('')}</defs>`);
  parts.push(`<rect width="${total}" height="${total}" fill="#000"/>`);
  const board = new Chess(fen).board();
  for (let r = 0; r < 8; r++) {
    for (let f = 0; f < 8; f++) {
      const square = `${'abcdefgh'[f]}${8 - r}`;
      const [x, y] = xy(square, flip);
      parts.push(`<rect x="${x}" y="${y}" width="${SQ}" height="${SQ}" fill="${(r + f) % 2 ? DARK : LIGHT}"/>`);
      const p = board[r][f];
      if (p) {
        const id = `${p.color === 'w' ? 'white' : 'black'}-${{ p: 'pawn', n: 'knight', b: 'bishop', r: 'rook', q: 'queen', k: 'king' }[p.type]}`;
        parts.push(`<use href="#${id}" xlink:href="#${id}" transform="translate(${x}, ${y})"/>`);
      }
    }
  }
  for (let i = 0; i < 8; i++) {
    const file = 'abcdefgh'[flip ? 7 - i : i], rank = String(flip ? i + 1 : 8 - i);
    const c = MARGIN + i * SQ + SQ / 2;
    parts.push(`<text x="${c}" y="14" fill="#fff" font-size="12" text-anchor="middle" font-family="monospace">${file}</text>`);
    parts.push(`<text x="${c}" y="${total - 5}" fill="#fff" font-size="12" text-anchor="middle" font-family="monospace">${file}</text>`);
    parts.push(`<text x="10" y="${c + 4}" fill="#fff" font-size="12" text-anchor="middle" font-family="monospace">${rank}</text>`);
    parts.push(`<text x="${total - 10}" y="${c + 4}" fill="#fff" font-size="12" text-anchor="middle" font-family="monospace">${rank}</text>`);
  }
  if (played) parts.push(arrow(played.slice(0, 2), played.slice(2, 4), PLAYED, flip));
  if (best && best !== played) parts.push(arrow(best.slice(0, 2), best.slice(2, 4), BEST, flip));
  parts.push('</svg>');
  return parts.join('');
}
