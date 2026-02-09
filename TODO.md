# Tasks TODO


## Performer Image Fields

Purpose: We want to add performer/band images to the intro video

2 type of images 

1. Add performer image field, `performer_image`
2. Add performer `logo` image field, `logo_image`
3. Update Performer discovery crawler to search for a grab an representative `performer_image` and `logo_image` 

Investigate TheAudioDB access, as is used by the KODI (open-source) project, and see if our registered artist info can be obtained from there.

## Update slides with performer images

Purpose: Make slides more visually appealing
Dependant on: "Performer Image Fields"


1. Add 'each' band's logo image to the first intro slide
2. Add the related band's performer_image to the associated performer slide.


## Update INTRO PROMPT to have a call to action for the selected Performers

Purpose: The call to action should be updated to request subscriptions/likes for the bands in the playlist. 

## Performer Genre Fields

Purpose: Allow future sorting by genre.

1. Add a Genre model 
2. Add ManyToMany relation field on perfomers to allow multiple `genres` be assigned to a Performer

## Performer Song/video Sample

Purpose: play in the background, or show a video clip when describing the artist.