// electron-builder afterPack hook: ad-hoc sign the Mac app.
//
// Without a paid Apple certificate electron-builder leaves the app unsigned,
// and since packaging changes Electron's bundle, its original signature
// breaks. macOS then calls the download "damaged". An ad-hoc signature fixes
// that: macOS instead asks once, under Privacy & Security > Open Anyway.

const { execFileSync } = require('node:child_process');
const path = require('node:path');

exports.default = async function adhocSign(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  const sign = target => execFileSync('codesign', ['--force', '--sign', '-', target], { stdio: 'inherit' });
  sign(path.join(app, 'Contents', 'Resources', 'stockfish', 'stockfish'));
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', app], { stdio: 'inherit' });
  execFileSync('codesign', ['--verify', '--deep', '--strict', '--verbose=2', app], { stdio: 'inherit' });
  console.log(`  • ad-hoc signed ${app}`);
};
