IMAGE := iain247/calibre-mcp-server
VERSION := $(shell git describe --tags --abbrev=0 2>/dev/null || echo "latest")

.PHONY: build push release tag dev

build:
	docker buildx build --platform linux/amd64,linux/arm64 -t $(IMAGE):$(VERSION) -t $(IMAGE):latest --push .

release: build

dev:
	docker buildx build --platform linux/amd64,linux/arm64 -t $(IMAGE):develop --push .

tag:
	@read -p "Version (e.g. 1.0.0): " v; git tag $$v && echo "Tagged $$v"
