import { ActionIcon, CopyButton, Group, Stack, Text, Tooltip } from "@mantine/core";
import { IconCheck, IconCopy, IconExternalLink } from "@tabler/icons-react";
import { useTranslation } from "react-i18next";

import type { MagnetLinkResponse } from "@/client/types.gen";

/** 标题优先; 没有标题时给出可辨认的磁力摘要, 完整地址只在复制时使用. */
function magnetLabel(magnet: MagnetLinkResponse): string {
  if (magnet.title) return magnet.title;
  if (magnet.info_hash) return `magnet:?xt=urn:btih:${magnet.info_hash}`;
  return magnet.url;
}

function publishedLabel(value: string | null | undefined, locale: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(date);
}

/** 影片详情页的磁力链接列表: 来源与发布时间作副标题, 复制与打开各一个动作. */
export function MagnetLinks({ magnets }: { magnets: MagnetLinkResponse[] }) {
  const { t, i18n } = useTranslation("metadata");
  if (magnets.length === 0) return null;

  return (
    <Stack gap={6}>
      {magnets.map((magnet) => {
        const label = magnetLabel(magnet);
        const meta = [magnet.feed_name, publishedLabel(magnet.published_at, i18n.language)]
          .filter((part): part is string => Boolean(part))
          .join(" · ");
        return (
          <Group key={magnet.id} gap="xs" wrap="nowrap" align="flex-start">
            <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
              <Text size="sm" truncate title={label}>
                {label}
              </Text>
              {meta && (
                <Text size="xs" c="dimmed" truncate>
                  {meta}
                </Text>
              )}
            </Stack>
            <CopyButton value={magnet.url} timeout={2000}>
              {({ copied, copy }) => (
                <Tooltip label={copied ? t("detail.magnetCopied") : t("detail.copyMagnet")}>
                  <ActionIcon
                    variant="subtle"
                    color={copied ? "teal" : "gray"}
                    onClick={copy}
                    aria-label={t("detail.copyMagnet")}
                  >
                    {copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
                  </ActionIcon>
                </Tooltip>
              )}
            </CopyButton>
            <Tooltip label={t("detail.openMagnet")}>
              <ActionIcon
                component="a"
                href={magnet.url}
                variant="subtle"
                color="gray"
                aria-label={t("detail.openMagnet")}
              >
                <IconExternalLink size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        );
      })}
    </Stack>
  );
}
