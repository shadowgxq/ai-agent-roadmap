import { useEffect } from 'react';

import { useTheme } from '../../shared/theme';

/**
 * 把当前主题写入 `<html data-theme>`，不渲染任何内容。
 * 与 index.html 的防闪烁脚本配合：脚本负责首帧，本组件负责后续切换。
 */
export function ThemeInitializer() {
  const { mode } = useTheme();

  useEffect(() => {
    document.documentElement.dataset.theme = mode;
  }, [mode]);

  return null;
}
