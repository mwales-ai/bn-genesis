#pragma once

#include <QWidget>
#include <QLabel>
#include <QSpinBox>
#include <QComboBox>
#include <QPushButton>
#include <QScrollArea>
#include <QGroupBox>
#include <QImage>
#include <QPixmap>
#include <QVector>
#include <QColor>
#include <QMap>

#include "binaryninjaapi.h"
#include "ui/sidebarwidget.h"
#include "ui/viewframe.h"

/**
 * Decodes Genesis 4bpp tile data and renders sprites.
 *
 * Genesis tile format:
 *   8x8 pixels, 4 bits per pixel, 32 bytes per tile
 *   2 pixels per byte (high nybble = left, low nybble = right)
 *   Sprites use column-major tile order: tile(col, row) = col * H + row
 *
 * CRAM palette format:
 *   16 colors x 2 bytes = 32 bytes
 *   Bit layout: ---- bbb- ggg- rrr- (3 bits per channel, 0-7 -> 0-252)
 */

#define SpriteViewerDebug if(0) std::cout

// ---------------------------------------------------------------------------
// Tile decoder helpers
// ---------------------------------------------------------------------------

/** Decode a single Genesis CRAM color word to QColor. */
QColor decodeCramColor(uint16_t cramWord);

/** Decode 32 bytes of CRAM palette data to 16 QColors. */
QVector<QColor> decodeCramPalette(const QByteArray & paletteBytes);

/** Decode a single 8x8 tile (32 bytes, 4bpp) to a QImage. */
QImage decodeTile(const QByteArray & tileBytes, const QVector<QColor> & palette);

/** Render a WxH grid of tiles as a QPixmap (column-major order). */
QPixmap renderSpriteGrid(const QByteArray & tileData, int widthTiles,
                          int heightTiles, const QVector<QColor> & palette,
                          int zoom);

/** Default 16-level grayscale palette. */
QVector<QColor> grayscalePalette();


// ---------------------------------------------------------------------------
// Palette swatch widget
// ---------------------------------------------------------------------------

class PaletteSwatchWidget : public QWidget
{
    Q_OBJECT
public:
    explicit PaletteSwatchWidget(QWidget *parent = nullptr);

    void setPalette(const QVector<QColor> & palette);

protected:
    void paintEvent(QPaintEvent *event) override;

private:
    QVector<QColor> thePalette;
    static const int SWATCH_SIZE = 16;
};


// ---------------------------------------------------------------------------
// Sprite viewer sidebar widget
// ---------------------------------------------------------------------------

class GenesisSpriteViewerWidget : public SidebarWidget
{
    Q_OBJECT
public:
    GenesisSpriteViewerWidget(const QString & title, ViewFrame *frame,
                               BinaryViewRef data);

    void notifyViewChanged(ViewFrame *frame) override;
    void notifyOffsetChanged(uint64_t offset) override;

private slots:
    void onGridChanged(int value);
    void onZoomChanged(int value);
    void onPaletteSelected(int index);
    void onLoadJson();
    void onReadPaletteAtCursor();

private:
    void buildUi();
    void refreshDisplay();

    BinaryViewRef      theData;
    ViewFrame         *theFrame;
    uint64_t           theCurrentOffset;

    int                theGridW;
    int                theGridH;
    int                theZoom;

    QVector<QColor>    theActivePalette;
    QMap<QString, QVector<QColor>> theLoadedPalettes;

    QLabel            *theAddrLabel;
    QSpinBox          *theWidthSpin;
    QSpinBox          *theHeightSpin;
    QSpinBox          *theZoomSpin;
    QComboBox         *thePaletteCombo;
    PaletteSwatchWidget *theSwatch;
    QLabel            *theSpriteDisplay;
    QLabel            *theInfoLabel;
};


// ---------------------------------------------------------------------------
// Sidebar widget type registration
// ---------------------------------------------------------------------------

class GenesisSpriteViewerWidgetType : public SidebarWidgetType
{
public:
    GenesisSpriteViewerWidgetType();

    SidebarWidgetLocation defaultLocation() const override
    {
        return SidebarWidgetLocation::RightContent;
    }

    SidebarContextSensitivity contextSensitivity() const override
    {
        return PerViewTypeSidebarContext;
    }

    SidebarWidget *createWidget(ViewFrame *frame, BinaryViewRef data) override;
};
