import { Plugin } from '@opencode/plugin';
import { startRuntime } from '../../plugin/runtime.js';

export default Plugin.define({
  id: '@yohi/opencode-plugin-chronos-turn-end',
  async setup(ctx) {
    return startRuntime(ctx);
  },
});
