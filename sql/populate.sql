-- Run by `make populate`, once per batch of parquet rows: every row becomes a document in the MongoDB collection.
-- Output must be newline-delimited JSON on stdout (streamed into mongoimport, nothing is written to disk).
-- The Makefile sets the variables: parquet (its URL), first_row and last_row (the batch, both included)
-- and xmin, ymin, xmax, ymax (the area whose pictures are kept, the whole world by default).
INSTALL spatial;
LOAD spatial;
-- the parquet is read over HTTP for a long time: retry a dropped read instead of ending the stream
SET http_retries = 10;
SET http_retry_wait_ms = 2000;
SET http_timeout = 120;
-- mongoimport does not need the rows in order: stream them instead of buffering them to keep it
SET preserve_insertion_order = false;

COPY (
    SELECT
        id AS _id,
        id,
        ST_AsGeoJSON(geometry)::JSON AS geometry,
        collection,
        created,
        datetime,
        "view:azimuth" AS azimuth,
        "quality:horizontal_accuracy" AS horizontal_accuracy,
        -- field_of_view and sensor_array_dimensions: needed to turn a box into a heading
        "pers:interior_orientation" AS interior_orientation,
        -- picture URLs by STAC role, hosted by each picture's own instance
        {
            'hd': list_filter(assets, lambda a: list_contains(a.roles, 'data'))[1].href,
            'sd': list_filter(assets, lambda a: list_contains(a.roles, 'visual'))[1].href,
            'thumb': list_filter(assets, lambda a: list_contains(a.roles, 'thumbnail'))[1].href
        } AS assets,
        semantics
    FROM read_parquet(getvariable('parquet'), file_row_number = true)
    -- only the row groups of the batch are downloaded
    WHERE file_row_number BETWEEN getvariable('first_row') AND getvariable('last_row')
        AND semantics IS NOT NULL AND azimuth IS NOT NULL
        -- the parquet is sorted by place: the row groups outside the area are skipped without being downloaded
        AND bbox.xmin BETWEEN getvariable('xmin') AND getvariable('xmax')
        AND bbox.ymin BETWEEN getvariable('ymin') AND getvariable('ymax')
) TO '/dev/stdout' (FORMAT json);
