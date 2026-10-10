"""Hugging Face adapters: new model weights and the HF blog.

These are marked disabled in the default config because huggingface.co is not
reachable from every network (notably mainland China without a proxy). Set
`enabled = true` once your proxy is up.
"""

from __future__ import annotations

from ..http import fetch_json
from .base import Source, SourceError


class HuggingFaceModelsSource(Source):
    """Newly created / trending model repositories."""

    type_name = "hf_models"

    def fetch(self) -> list[Item]:
        sort = str(self.config.opt("sort", "createdAt"))
        limit = int(self.config.opt("limit", 40))
        pipeline = self.config.opt("pipeline_tag")
        min_likes = int(self.config.opt("min_likes", 0))
        min_downloads = int(self.config.opt("min_downloads", 0))

        params: dict[str, object] = {
            "sort": sort,
            "direction": -1,
            "limit": limit,
            "full": "false",
        }
        if pipeline:
            params["filter"] = pipeline

        url = "https://huggingface.co/api/models"
        query = "&".join(
            f"{k}={v}" for k, v in params.items()
        )
        data = fetch_json(f"{url}?{query}", timeout=30, retries=2)
        if not isinstance(data, list):
            raise SourceError("unexpected Hugging Face models response")

        items: list[Item] = []
        for model in data:
            if not isinstance(model, dict):
                continue
            model_id = str(model.get("modelId") or model.get("id") or "")
            if not model_id:
                continue
            likes = int(model.get("likes") or 0)
            downloads = int(model.get("downloads") or 0)
            if likes < min_likes or downloads < min_downloads:
                continue

            tags = [str(t) for t in (model.get("tags") or [])][:12]
            items.append(
                self.make_item(
                    title=model_id,
                    url=f"https://huggingface.co/{model_id}",
                    summary=f"Model on Hugging Face. Likes: {likes}, "
                    f"downloads: {downloads}. Tags: {', '.join(tags[:8])}",
                    published=model.get("createdAt"),
                    tags=tags,
                    stars=likes,
                    extra_id=f"hf-{model_id}",
                )
            )
        return items


class HuggingFaceBlogSource(Source):
    type_name = "hf_blog"

    def fetch(self) -> list[Item]:
        from .base import parse_feed
        from ..http import fetch_text

        text = fetch_text(self.config.url, timeout=30, retries=2)
        limit = int(self.config.opt("limit", 25))
        items = []
        for entry in parse_feed(text)[:limit]:
            if not entry.title:
                continue
            items.append(
                self.make_item(
                    title=entry.title,
                    url=entry.link,
                    summary=entry.summary,
                    published=entry.published,
                    authors=entry.authors,
                    tags=entry.tags,
                )
            )
        return items
