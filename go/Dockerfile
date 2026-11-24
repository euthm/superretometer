# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.25-alpine AS build
ARG TARGETOS=linux
ARG TARGETARCH=amd64
ARG REVISION=development
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath \
    -ldflags="-s -w -X main.revision=$REVISION" \
    -o /out/superretometer ./cmd/superretometer

FROM alpine:3.23
RUN apk add --no-cache ca-certificates \
    && addgroup -g 10001 -S superretometer \
    && adduser -u 10001 -S -G superretometer superretometer \
    && mkdir /data && chown 10001:10001 /data
COPY --from=build /out/superretometer /usr/local/bin/superretometer
USER 10001:10001
VOLUME ["/data"]
EXPOSE 3010
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["/usr/local/bin/superretometer", "--healthcheck"]
ENTRYPOINT ["/usr/local/bin/superretometer"]
# Supply a token, or use compose.yaml with an authenticated proxy.
CMD ["mcp", "--state", "/data/state.json", "--listen", "0.0.0.0:3010"]
